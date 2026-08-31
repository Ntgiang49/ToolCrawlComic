import os
import re
import shutil
import time
from urllib.parse import urlparse
from typing import List, Dict, Any, Tuple

import requests
import cloudscraper  # Đã thêm thư viện vượt Cloudflare
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from .config_loader import ConfigLoader
from .exporter import ComicExporter
from .chapter_namer import ChapterNamer
from .image_processor import ImageProcessor
from .utils import sanitize_filename, make_absolute_url


try:
    import lxml  # noqa: F401
    HTML_PARSER = "lxml"
except ImportError:
    HTML_PARSER = "html.parser"


from requests.adapters import HTTPAdapter


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
        
        # Thay thế requests.Session() bằng cloudscraper để vượt qua Anti-bot
        self.session = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        
        pool_size = max(10, num_threads * 2)
        adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        if hasattr(self, "session") and self.session:
            self.session.close()

    def _fetch_html(self, url: str, headers: Dict[str, str]) -> str:
        """Fetches HTML content with automatic retries."""
        last_error = None
        for attempt in range(5):
            try:
                response = self.session.get(url, headers=headers, timeout=15)
                response.raise_for_status()
                return response.text
            except requests.RequestException as e:
                last_error = e
                if attempt == 4:
                    break
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Failed to fetch {url} after 5 attempts: {last_error}")

    def parse_comic_info(self, comic_url: str) -> Dict[str, Any]:
        """Fetches and parses main comic landing page metadata and chapter list."""
        site_config = self.config_loader.get_site_config(comic_url)
        headers = site_config["headers"].copy()

        html = self._fetch_html(comic_url, headers)
        soup = BeautifulSoup(html, HTML_PARSER)
        selectors = site_config["selectors"]

        # Parse Title
        title = "Unknown Comic"
        title_tag = soup.select_one(selectors.get("comic_title", selectors.get("title", "h1")))
        if title_tag:
            title = sanitize_filename(title_tag.get_text(strip=True))

        # Parse Author
        author = "Unknown"
        author_sel = selectors.get("author")
        if author_sel:
            tag = soup.select_one(author_sel)
            if tag:
                author = _clean_field(tag.get_text(strip=True), selectors.get("author_prefix", "Tác giả"))

        # Parse Category / Genre
        category = "Unknown"
        cat_sel = selectors.get("category")
        if cat_sel:
            tags = soup.select(cat_sel)
            if tags:
                cats = [_clean_field(t.get_text(strip=True), selectors.get("category_prefix", "Thể loại")) for t in tags]
                category = ", ".join([c for c in cats if c and c != "Unknown"]) or "Unknown"

        # Parse Description
        description = ""
        desc_sel = selectors.get("description")
        if desc_sel:
            tag = soup.select_one(desc_sel)
            if tag:
                description = _clean_field(tag.get_text(strip=True), selectors.get("description_prefix", "Nội dung"))

        # Parse Chapters
        raw_chapters = []
        seen_urls = set()
        ch_nodes = soup.select(selectors.get("chapter_list", ".chapter a"))
        blacklist = [b.lower() for b in site_config.get("chapter_title_blacklist", [])]
        comic_path = urlparse(comic_url).path.rstrip("/")
        filter_same = selectors.get("filter_same_comic", True)

        for node in ch_nodes:
            ch_url = node.get("href")
            if not ch_url or ch_url.strip() in ("#", "javascript:void(0)"):
                continue

            ch_title = node.get_text(strip=True)
            if not ch_title or any(b in ch_title.lower() for b in blacklist):
                continue

            abs_url = make_absolute_url(comic_url, ch_url)

            # Filter out sidebar/widget chapters from other comics
            if filter_same and comic_path and not urlparse(abs_url).path.startswith(comic_path):
                continue

            if abs_url not in seen_urls:
                seen_urls.add(abs_url)
                raw_chapters.append({"raw_title": ch_title, "url": abs_url})

        # Apply configurable chapter order (default: desc in raw order)
        order = site_config.get("chapter_order", "desc").lower()
        if order == "desc" and raw_chapters:
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
            "title": title,
            "author": author,
            "category": category,
            "description": description,
            "chapters": chapters,
            "site_config": site_config,
        }

    def extract_chapter_images(self, chapter_url: str, site_config: Dict[str, Any]) -> List[str]:
        """Extracts list of raw image URLs from a chapter reader page."""
        headers = site_config["headers"].copy()
        html = self._fetch_html(chapter_url, headers)

        soup = BeautifulSoup(html, HTML_PARSER)
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

        if os.path.isfile(target) and os.path.getsize(target) > 0:
            return True, target
        if os.path.isdir(target) and any(os.scandir(target)):
            return True, target
        return False, target

    def download_image(self, img_url: str, save_path: str, headers: Dict[str, str], optimize: bool = True) -> bool:
        """Downloads a single image file with retries and inline WebP optimization."""
        for attempt in range(3):
            try:
                res = self.session.get(img_url, headers=headers, timeout=15)
                res.raise_for_status()
                raw_bytes = res.content
                if not raw_bytes:
                    return False

                if optimize:
                    try:
                        processed = ImageProcessor.process_image(raw_bytes)
                        base, _ = os.path.splitext(save_path)
                        final_save_path = f"{base}.{processed.format}"
                        with open(final_save_path, "wb") as f:
                            f.write(processed.buffer)
                        return True
                    except Exception:
                        pass

                with open(save_path, "wb") as f:
                    f.write(raw_bytes)
                return True
            except Exception:
                if attempt == 2:
                    return False
                time.sleep(1)
        return False

    def _download_image_with_error(
        self, img_url: str, save_path: str, headers: Dict[str, str]
    ) -> Tuple[bool, str]:
        """Downloads an image and preserves a useful failure reason for callers."""
        for attempt in range(3):
            try:
                res = self.session.get(img_url, headers=headers, timeout=15)
                res.raise_for_status()
                if not res.content:
                    raise RuntimeError("empty response body")

                processed = ImageProcessor.process_image(res.content)
                base, _ = os.path.splitext(save_path)
                final_save_path = f"{base}.{processed.format}"
                with open(final_save_path, "wb") as f:
                    f.write(processed.buffer)
                return True, ""
            except Exception as exc:
                if attempt == 2:
                    return False, str(exc)
                time.sleep(1)
        return False, "unknown download error"

    def download_chapter(
        self,
        chapter_title: str,
        chapter_url: str,
        site_config: Dict[str, Any],
        output_dir: str,
        export_format: str = "images"
    ) -> Tuple[bool, str]:
        """Downloads all images of a chapter concurrently with inline WebP optimization."""
        already_exists, _ = self.is_chapter_downloaded(chapter_title, output_dir, export_format)
        if already_exists:
            return True, f"[Skipped] {chapter_title} (Already exists)"

        image_urls = self.extract_chapter_images(chapter_url, site_config)
        if not image_urls:
            return False, f"No image URLs found for chapter: {chapter_title}"

        ch_name = sanitize_filename(chapter_title)
        temp_dir = os.path.join(output_dir, "_temp", ch_name)
        os.makedirs(temp_dir, exist_ok=True)

        headers = site_config["headers"].copy()
        # Image CDNs commonly reject hotlink requests without the reader page as referer.
        headers["Referer"] = chapter_url

        with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
            tasks = []
            for idx, img_url in enumerate(image_urls):
                save_path = os.path.join(temp_dir, f"{idx + 1:03d}.webp")
                tasks.append(executor.submit(self._download_image_with_error, img_url, save_path, headers))

            failures = []
            for task in tqdm(as_completed(tasks), total=len(tasks), desc=f"Downloading {ch_name[:20]}", leave=False):
                success, error = task.result()
                if not success and error:
                    failures.append(error)

        valid_paths = [
            os.path.join(temp_dir, f)
            for f in sorted(os.listdir(temp_dir))
            if os.path.isfile(os.path.join(temp_dir, f)) and os.path.getsize(os.path.join(temp_dir, f)) > 0
        ]
        if not valid_paths:
            reason = failures[0] if failures else "unknown download error"
            return False, f"Failed to download images for {chapter_title}: {reason}"

        try:
            if export_format in ("cbz", "pdf"):
                ComicExporter._export_to_target(valid_paths, os.path.join(output_dir, ch_name), export_format)
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