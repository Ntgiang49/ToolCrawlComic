#!/usr/bin/env python3
"""Full chapter crawl: enumerate every /chuong-N URL up to the visible max,
download every chapter the page list never shows (gaps, old chapters)."""

import io
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", write_through=True
    )

from concurrent.futures import ThreadPoolExecutor
import requests
from comic_crawler.core import ComicCrawler
from comic_crawler.library import LibraryManager
from comic_crawler.chapter_namer import ChapterNamer

OUT = os.environ.get("DOWNLOADS_DIR", "downloads")


def enumerate_valid(session: requests.Session, comic_url: str, max_n: int) -> list[int]:
    """Concurrent probe of /chuong-1..max_n; returns numbers that resolve."""
    base = comic_url.rstrip("/") + "/chuong-"
    comic_path = urlparse(comic_url).path.rstrip("/")

    def _check_ch(n: int) -> int | None:
        try:
            r = session.get(base + str(n), timeout=15, allow_redirects=True)
            final_path = urlparse(r.url).path
            if final_path.startswith(comic_path + "/chuong-"):
                return n
        except requests.RequestException:
            pass
        return None

    with ThreadPoolExecutor(max_workers=16) as executor:
        valid = [res for res in executor.map(_check_ch, range(1, max_n + 1)) if res is not None]
    print(f"  Probed 1..{max_n} -> found {len(valid)} valid chapters", flush=True)
    return sorted(valid)


def main() -> None:
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    target_url = next((arg for arg in sys.argv[1:] if arg.startswith("http://") or arg.startswith("https://")), None)
    target_comic = None
    if "--comic" in sys.argv:
        idx = sys.argv.index("--comic")
        if idx + 1 < len(sys.argv):
            target_comic = sys.argv[idx + 1].strip().lower()

    export_format = "images"
    if "-f" in sys.argv:
        idx = sys.argv.index("-f")
        if idx + 1 < len(sys.argv):
            export_format = sys.argv[idx + 1].strip().lower()
    elif "--format" in sys.argv:
        idx = sys.argv.index("--format")
        if idx + 1 < len(sys.argv):
            export_format = sys.argv[idx + 1].strip().lower()

    lib_manager = LibraryManager()
    library = lib_manager.get_all_comics()

    if target_url:
        library = {target_url: {"title": target_url, "url": target_url}}
    elif target_comic:
        library = {
            url: item for url, item in library.items()
            if target_comic in item.get("title", "").lower() or target_comic in url.lower()
        }

    if not library:
        print("No matching comics found.")
        return

    crawler = ComicCrawler()
    try:
        for url, item in library.items():
            title = item.get("title", url)
            print(f"\n=== {title} ===", flush=True)
            info = crawler.parse_comic_info(url)
            site_config = info["site_config"]
            lib_manager.add_or_update_comic(url, info["title"], export_format="images")

            out_dir = Path(OUT) / info["title"]
            out_dir.mkdir(parents=True, exist_ok=True)

            meta = {
                "url": url,
                "title": info["title"],
                "author": info.get("author", "Unknown"),
                "category": info.get("category", "Unknown"),
                "description": info.get("description", "")
            }
            (out_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            nums = []
            for ch in info["chapters"]:
                m = re.search(r"chuong-([0-9.]+)$", ch["url"])
                if m:
                    nums.append(int(float(m.group(1))))
            if not nums:
                print("  No chapter numbers parsed, skipping")
                continue
            max_n = max(nums)
            probe_to = max_n
            print(f"  Visible max chapter: {max_n} (page shows {len(nums)} links)")

            headers = dict(site_config.get("headers", {}))
            headers.setdefault(
                "User-Agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            )
            session = requests.Session()
            session.headers.update(headers)

            existing = {
                int(ChapterNamer.extract_number(d.name))
                for d in out_dir.iterdir()
                if ChapterNamer.extract_number(d.name) is not None
            }
            print(f"  Enumeration 1..{probe_to}...")
            valid = enumerate_valid(session, url, probe_to)
            missing = [n for n in valid if n not in existing]
            if limit:
                missing = missing[:limit]
            print(f"  {len(valid)} exist, {len(existing)} already local, {len(missing)} to download")

            base = url.rstrip("/") + "/chuong-"
            new_count = 0
            for i, n in enumerate(missing, 1):
                ch_name = ChapterNamer.format_chapter_name(f"Chapter {n}", total_chapters=max_n)
                print(f"  [{i}/{len(missing)}] {ch_name} ({export_format.upper()})...", flush=True)
                success, msg = crawler.download_chapter(
                    ch_name, base + str(n), site_config, str(out_dir), export_format
                )
                if success:
                    new_count += 1
                    print(f"  [OK] {ch_name} saved", flush=True)
                else:
                    print(f"  [Failed] {ch_name}: {msg}", flush=True)
            print(f"  Downloaded {new_count} new chapter(s)", flush=True)
    finally:
        crawler.close()


if __name__ == "__main__":
    main()
