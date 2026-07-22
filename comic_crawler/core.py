import os
import re
import time
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Tuple
from tqdm import tqdm

from .config_loader import ConfigLoader
from .exporter import ComicExporter
from .chapter_namer import ChapterNamer
from .utils import sanitize_filename, make_absolute_url

class ComicCrawler:
    def __init__(self, config_path: str = "config.json", num_threads: int = 4):
        self.config_loader = ConfigLoader(config_path)
        self.num_threads = num_threads
        self.session = requests.Session()

    def _fetch_html(self, url: str, headers: Dict[str, str]) -> str:
        """
        Fetches HTML content with automatic retries.
        """
        retries = 3
        for attempt in range(retries):
            try:
                response = self.session.get(url, headers=headers, timeout=15)
                response.raise_for_status()
                return response.text
            except requests.RequestException as e:
                if attempt == retries - 1:
                    raise RuntimeError(f"Failed to fetch {url}: {e}")
                time.sleep(1.5 * (attempt + 1))
        return ""

    def parse_comic_info(self, url: str) -> Dict[str, Any]:
        """
        Parses main comic page to extract title and list of chapters.
        Returns: { "title": str, "chapters": [ {"title": str, "url": str} ] }
        """
        site_config = self.config_loader.get_site_config(url)
        headers = site_config["headers"]
        selectors = site_config["selectors"]

        html = self._fetch_html(url, headers)
        soup = BeautifulSoup(html, "lxml" if "lxml" in BeautifulSoup.__dict__ else "html.parser")

        # 1. Extract Comic Title
        title_elem = soup.select_one(selectors.get("comic_title", "h1"))
        comic_title = title_elem.get_text(strip=True) if title_elem else "Unknown_Comic"
        comic_title = sanitize_filename(comic_title)

        # 2. Extract Chapter Links
        chapter_nodes = soup.select(selectors.get("chapter_list", "a[href*='chapter']"))
        raw_chapters = []

        for idx, node in enumerate(chapter_nodes):
            href = node.get("href")
            if not href:
                continue
            abs_url = make_absolute_url(url, href)
            raw_title = node.get_text(strip=True) or f"Chapter_{idx + 1}"
            
            if not any(ch["url"] == abs_url for ch in raw_chapters):
                raw_chapters.append({
                    "raw_title": raw_title,
                    "url": abs_url
                })

        # Most manga sites list newest chapters first, reverse to get chronological order (1 to N)
        if raw_chapters:
            raw_chapters.reverse()

        total_count = len(raw_chapters)
        chapters = []
        for idx, ch in enumerate(raw_chapters, 1):
            formatted_title = ChapterNamer.format_chapter_name(ch["raw_title"], total_chapters=total_count)
            chapters.append({
                "title": sanitize_filename(formatted_title),
                "url": ch["url"]
            })

        return {
            "title": comic_title,
            "chapters": chapters,
            "site_config": site_config
        }

    def extract_chapter_images(self, chapter_url: str, site_config: Dict[str, Any]) -> List[str]:
        """
        Extracts image URLs from a specific chapter page.
        """
        headers = site_config["headers"]
        selectors = site_config["selectors"]

        html = self._fetch_html(chapter_url, headers)
        soup = BeautifulSoup(html, "html.parser")

        image_urls = []
        img_nodes = soup.select(selectors.get("page_images", "img"))
        attrs_to_check = selectors.get("image_url_attributes", ["src", "data-src", "data-lazy-src", "data-original"])

        for node in img_nodes:
            img_src = None
            for attr in attrs_to_check:
                val = node.get(attr)
                if val and not val.startswith("data:image"): # ignore base64 placeholders
                    img_src = val
                    break
            
            if img_src:
                abs_img_url = make_absolute_url(chapter_url, img_src)
                if abs_img_url not in image_urls:
                    image_urls.append(abs_img_url)

        return image_urls

    def is_chapter_downloaded(self, chapter_title: str, output_dir: str, export_format: str) -> Tuple[bool, str]:
        """
        Checks if a chapter file or directory already exists locally and is non-empty.
        """
        ch_dir_name = sanitize_filename(chapter_title)
        if export_format == "cbz":
            target = os.path.join(output_dir, f"{ch_dir_name}.cbz")
        elif export_format == "pdf":
            target = os.path.join(output_dir, f"{ch_dir_name}.pdf")
        else: # images
            target = os.path.join(output_dir, ch_dir_name)

        if os.path.exists(target):
            if os.path.isfile(target) and os.path.getsize(target) > 0:
                return True, target
            elif os.path.isdir(target) and len(os.listdir(target)) > 0:
                return True, target
        return False, target

    def download_image(self, img_url: str, save_path: str, headers: Dict[str, str]) -> bool:
        """
        Downloads a single image file.
        """
        for attempt in range(3):
            try:
                res = self.session.get(img_url, headers=headers, timeout=15, stream=True)
                res.raise_for_status()
                with open(save_path, "wb") as f:
                    for chunk in res.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
            except Exception:
                if attempt == 2:
                    return False
                time.sleep(1)
        return False

    def download_chapter(
        self, 
        chapter_title: str, 
        chapter_url: str, 
        site_config: Dict[str, Any], 
        output_dir: str,
        export_format: str = "images"
    ) -> Tuple[bool, str]:
        """
        Downloads all images of a chapter concurrently and exports to specified format.
        Options for export_format: "images", "cbz", "pdf"
        """
        # Incremental sync check - skip if chapter file already exists locally!
        already_exists, existing_path = self.is_chapter_downloaded(chapter_title, output_dir, export_format)
        if already_exists:
            return True, f"[Skipped] {chapter_title} (Already exists)"

        image_urls = self.extract_chapter_images(chapter_url, site_config)
        if not image_urls:
            return False, f"No image URLs found for chapter: {chapter_title}"

        # Temporary folder for raw chapter images
        ch_dir_name = sanitize_filename(chapter_title)
        temp_ch_dir = os.path.join(output_dir, "_temp", ch_dir_name)
        os.makedirs(temp_ch_dir, exist_ok=True)

        download_tasks = []
        downloaded_paths = []

        headers = site_config["headers"].copy()

        # Multi-threaded download
        with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
            for idx, img_url in enumerate(image_urls):
                ext = os.path.splitext(img_url.split("?")[0])[1]
                if ext.lower() not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
                    ext = ".jpg"

                filename = f"{idx + 1:03d}{ext}"
                save_path = os.path.join(temp_ch_dir, filename)
                downloaded_paths.append(save_path)

                task = executor.submit(self.download_image, img_url, save_path, headers)
                download_tasks.append(task)

            # Progress tracking with tqdm
            desc = f"Downloading {ch_dir_name[:20]}"
            for _ in tqdm(as_completed(download_tasks), total=len(download_tasks), desc=desc, leave=False):
                pass

        # Verify downloads
        valid_paths = [p for p in downloaded_paths if os.path.exists(p) and os.path.getsize(p) > 0]
        if not valid_paths:
            return False, f"Failed to download images for {chapter_title}"

        final_dest = ""
        # Handle Output Export Formats
        if export_format == "cbz":
            final_dest = os.path.join(output_dir, f"{ch_dir_name}.cbz")
            ComicExporter.export_to_cbz(valid_paths, final_dest)
            self._cleanup_temp(temp_ch_dir)
        elif export_format == "pdf":
            final_dest = os.path.join(output_dir, f"{ch_dir_name}.pdf")
            ComicExporter.export_to_pdf(valid_paths, final_dest)
            self._cleanup_temp(temp_ch_dir)
        else: # "images" / folder format
            final_dest = os.path.join(output_dir, ch_dir_name)
            os.makedirs(final_dest, exist_ok=True)
            for path in valid_paths:
                dest_file = os.path.join(final_dest, os.path.basename(path))
                if os.path.exists(dest_file):
                    os.remove(dest_file)
                os.rename(path, dest_file)
            self._cleanup_temp(temp_ch_dir)

        return True, final_dest

    def _cleanup_temp(self, temp_dir: str):
        try:
            if os.path.exists(temp_dir):
                for f in os.listdir(temp_dir):
                    os.remove(os.path.join(temp_dir, f))
                os.rmdir(temp_dir)
        except Exception:
            pass
