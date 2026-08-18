import os
import re
import shutil
import time
from urllib.parse import urlparse
from typing import List, Dict, Any, Tuple

import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from .config_loader import ConfigLoader
from .exporter import ComicExporter
from .chapter_namer import ChapterNamer
from .utils import sanitize_filename, make_absolute_url


def _clean_field(text: str, prefix: str = "") -> str:
    """Strip prefix, leading colon/whitespace, and trailing spaces."""
    if not text:
        return ""
    text = text.strip()
    if prefix and text.startswith(prefix):
        text = text[len(prefix):]
    return text.lstrip(": ").strip()


class ComicCrawler:
    def __init__(self, config_path: str = "config.json", num_threads: int = 4):
        self.config_loader = ConfigLoader(config_path)
        self.num_threads = num_threads
        self.session = requests.Session()

    def _fetch_html(self, url: str, headers: Dict[str, str]) -> str:
        """Fetches HTML content with automatic retries."""
        for attempt in range(3):
            try:
                response = self.session.get(url, headers=headers, timeout=15)
                response.raise_for_status()
                return response.text
            except requests.RequestException as e:
                if attempt == 2:
                    raise RuntimeError(f"Failed to fetch {url}: {e}")
                time.sleep(1.5 * (attempt + 1))
        return ""

    def parse_comic_info(self, url: str) -> Dict[str, Any]:
        """Parses main comic page to extract title, metadata, and chapters."""
        site_config = self.config_loader.get_site_config(url)
        headers = site_config["headers"]
        selectors = site_config["selectors"]

        html = self._fetch_html(url, headers)
        soup = BeautifulSoup(html, "lxml" if "lxml" in BeautifulSoup.__dict__ else "html.parser")

        # 1. Title
        title_elem = soup.select_one(selectors.get("comic_title", "h1"))
        comic_title = sanitize_filename(title_elem.get_text(strip=True)) if title_elem else "Unknown_Comic"

        # 2. Author
        author_elem = soup.select_one(selectors.get("author", "")) if selectors.get("author") else None
        author_raw = author_elem.get_text(strip=True) if author_elem else ""
        author = _clean_field(author_raw, selectors.get("author_prefix", "")) or "Unknown"

        # 3. Category / Genre
        category = "Unknown"
        if selectors.get("category"):
            cat_nodes = soup.select(selectors["category"])
            cats = [_clean_field(c.get_text(strip=True), selectors.get("category_prefix", "")) for c in cat_nodes]
            cats = [c for c in cats if c]
            if cats:
                category = ", ".join(cats)

        # 4. Description
        description = ""
        if selectors.get("description"):
            desc_elem = soup.select_one(selectors["description"])
            if desc_elem:
                description = _clean_field(desc_elem.get_text(strip=True), selectors.get("description_prefix", ""))

        # 5. Chapter Links
        chapter_nodes = soup.select(selectors.get("chapter_list", "a[href*='chapter']"))
        filter_same = selectors.get("filter_same_comic", False)
        title_blacklist = selectors.get("chapter_title_blacklist", [])
        comic_path = urlparse(url).path.rstrip("/") + "/"
        raw_chapters = []

        for idx, node in enumerate(chapter_nodes):
            href = node.get("href")
            if not href or href.strip() in ("#", "javascript:void(0)"):
                continue
            abs_url = make_absolute_url(url, href)
            if filter_same and not urlparse(abs_url).path.startswith(comic_path):
                continue
            raw_title = node.get_text(strip=True) or f"Chapter_{idx + 1}"
            if raw_title in title_blacklist:
                continue
            if not re.search(r"\d", raw_title):
                m = re.search(r"chuong-([0-9.]+)", href)
                if m:
                    raw_title = f"Chapter {m.group(1)}"

            if not any(ch["url"] == abs_url for ch in raw_chapters):
                raw_chapters.append({"raw_title": raw_title, "url": abs_url})

        # Chronological order (1 to N)
        if raw_chapters:
            raw_chapters.reverse()

        total_count = len(raw_chapters)
        chapters = [
            {
                "title": sanitize_filename(ChapterNamer.format_chapter_name(ch["raw_title"], total_chapters=total_count)),
                "url": ch["url"]
            }
            for ch in raw_chapters
        ]

        return {
            "title": comic_title,
            "author": author,
            "category": category,
            "description": description,
            "chapters": chapters,
            "site_config": site_config
        }

    def extract_chapter_images(self, chapter_url: str, site_config: Dict[str, Any]) -> List[str]:
        """Extracts image URLs from a specific chapter page."""
        html = self._fetch_html(chapter_url, site_config["headers"])
        soup = BeautifulSoup(html, "html.parser")

        selectors = site_config["selectors"]
        img_nodes = soup.select(selectors.get("page_images", "img"))
        attrs = selectors.get("image_url_attributes", ["src", "data-src", "data-lazy-src", "data-original"])

        image_urls = []
        for node in img_nodes:
            src = next((node.get(a) for a in attrs if node.get(a) and not node.get(a).startswith("data:image")), None)
            if src:
                abs_url = make_absolute_url(chapter_url, src)
                if abs_url not in image_urls:
                    image_urls.append(abs_url)

        return image_urls

    def is_chapter_downloaded(self, chapter_title: str, output_dir: str, export_format: str) -> Tuple[bool, str]:
        """Checks if a chapter file or directory already exists locally and is non-empty."""
        ch_name = sanitize_filename(chapter_title)
        ext_map = {"cbz": ".cbz", "pdf": ".pdf"}
        target = os.path.join(output_dir, f"{ch_name}{ext_map[export_format]}") if export_format in ext_map else os.path.join(output_dir, ch_name)

        if os.path.exists(target):
            if os.path.isfile(target) and os.path.getsize(target) > 0:
                return True, target
            if os.path.isdir(target) and len(os.listdir(target)) > 0:
                return True, target
        return False, target

    def download_image(self, img_url: str, save_path: str, headers: Dict[str, str]) -> bool:
        """Downloads a single image file with retries."""
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
        """Downloads all images of a chapter concurrently and exports to format."""
        already_exists, _ = self.is_chapter_downloaded(chapter_title, output_dir, export_format)
        if already_exists:
            return True, f"[Skipped] {chapter_title} (Already exists)"

        image_urls = self.extract_chapter_images(chapter_url, site_config)
        if not image_urls:
            return False, f"No image URLs found for chapter: {chapter_title}"

        ch_name = sanitize_filename(chapter_title)
        temp_dir = os.path.join(output_dir, "_temp", ch_name)
        os.makedirs(temp_dir, exist_ok=True)

        downloaded_paths = []
        headers = site_config["headers"].copy()

        with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
            tasks = []
            for idx, img_url in enumerate(image_urls):
                ext = os.path.splitext(img_url.split("?")[0])[1]
                if ext.lower() not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
                    ext = ".jpg"
                save_path = os.path.join(temp_dir, f"{idx + 1:03d}{ext}")
                downloaded_paths.append(save_path)
                tasks.append(executor.submit(self.download_image, img_url, save_path, headers))

            for _ in tqdm(as_completed(tasks), total=len(tasks), desc=f"Downloading {ch_name[:20]}", leave=False):
                pass

        valid_paths = [p for p in downloaded_paths if os.path.exists(p) and os.path.getsize(p) > 0]
        if not valid_paths:
            return False, f"Failed to download images for {chapter_title}"

        try:
            if export_format == "cbz":
                ComicExporter.export_to_cbz(valid_paths, os.path.join(output_dir, f"{ch_name}.cbz"))
            elif export_format == "pdf":
                ComicExporter.export_to_pdf(valid_paths, os.path.join(output_dir, f"{ch_name}.pdf"))
            else:
                final_dest = os.path.join(output_dir, ch_name)
                os.makedirs(final_dest, exist_ok=True)
                for path in valid_paths:
                    dest_file = os.path.join(final_dest, os.path.basename(path))
                    if os.path.exists(dest_file):
                        os.remove(dest_file)
                    os.rename(path, dest_file)
        finally:
            self._cleanup_temp(temp_dir)

        return True, os.path.join(output_dir, ch_name)

    def _cleanup_temp(self, temp_dir: str) -> None:
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
