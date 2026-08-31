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


def extract_chapter_number(chapter: dict) -> float | int | None:
    """Extract a chapter number from its title, then from a chapter URL."""
    title_number = ChapterNamer.extract_number(chapter.get("title", ""))
    if title_number is not None:
        return int(title_number) if title_number.is_integer() else title_number

    url = chapter.get("url", "")
    match = re.search(
        r"(?:chapter|chap|chuong|chương|ch)[/_-]*(\d+(?:\.\d+)?)",
        url,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = float(match.group(1))
    return int(value) if value.is_integer() else value


def enumerate_valid(session: requests.Session, comic_url: str, max_n: int) -> list[int]:
    """Concurrent probe of /chuong-1..max_n; returns numbers that resolve."""
    base = comic_url.rstrip("/") + "/chuong-"
    comic_path = urlparse(comic_url).path.rstrip("/")

    def _check_ch(n: int) -> int | None:
        try:
            r = session.get(base + str(n), timeout=15, allow_redirects=True)
            if not r.ok:
                return None
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


def chapter_urls_by_number(chapters: list[dict]) -> dict[float | int, str]:
    """Index parsed chapter URLs by chapter number, including decimals."""
    return {
        number: chapter["url"]
        for chapter in chapters
        if (number := extract_chapter_number(chapter)) is not None
    }


def chapter_key(number: float | int) -> str:
    """Return a stable JSON key for a chapter number."""
    return str(number)


def load_chapter_manifest(meta: dict) -> dict[str, dict]:
    """Read the per-comic chapter manifest, tolerating older metadata files."""
    manifest = meta.get("chapters", {})
    if isinstance(manifest, list):
        return {
            chapter_key(item["number"]): item
            for item in manifest
            if isinstance(item, dict) and item.get("number") is not None
        }
    return manifest if isinstance(manifest, dict) else {}


def save_meta(meta_path: Path, meta: dict) -> None:
    """Persist metadata atomically so the manifest survives interruptions."""
    temp_path = meta_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(meta_path)


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
                "description": info.get("description", ""),
            }
            meta_path = out_dir / "meta.json"
            if meta_path.exists():
                try:
                    old_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    if isinstance(old_meta, dict):
                        meta["chapters"] = old_meta.get("chapters", {})
                except (json.JSONDecodeError, OSError):
                    pass
            manifest = load_chapter_manifest(meta)
            meta["chapters"] = manifest

            nums = []
            for ch in info["chapters"]:
                chapter_number = extract_chapter_number(ch)
                if chapter_number is not None:
                    nums.append(chapter_number)
            if not nums:
                print("  No chapter numbers parsed, skipping")
                continue
            max_n = max(nums)
            probe_to = int(max_n)
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
                number
                for d in out_dir.iterdir()
                if (number := ChapterNamer.extract_number(d.name)) is not None
            }
            parsed_urls = chapter_urls_by_number(info["chapters"])
            if len(parsed_urls) >= probe_to:
                valid = sorted(parsed_urls)
                print(f"  Using {len(valid)} chapter URLs from page")
            else:
                print(f"  Enumeration 1..{probe_to}...")
                probed = enumerate_valid(session, url, probe_to)
                valid = sorted(set(parsed_urls) | set(probed))
            for number in valid:
                key = chapter_key(number)
                entry = manifest.setdefault(key, {"number": number, "synced": False})
                entry.update({
                    "number": number,
                    "title": entry.get("title") or f"Chapter {number}",
                    "url": parsed_urls.get(number, f"{url.rstrip('/')}/chuong-{number}"),
                    "local_name": entry.get("local_name") or ChapterNamer.format_chapter_name(
                        f"Chapter {number}", total_chapters=max_n
                    ),
                    "format": entry.get("format") or export_format,
                    "synced": bool(entry.get("synced", False)),
                })
            save_meta(meta_path, meta)

            missing = [
                n for n in valid
                if n not in existing and not manifest[chapter_key(n)].get("synced", False)
            ]
            if limit:
                missing = missing[:limit]
            print(f"  {len(valid)} exist, {len(existing)} already local, {len(missing)} to download")

            new_count = 0
            for i, n in enumerate(missing, 1):
                ch_name = ChapterNamer.format_chapter_name(f"Chapter {n}", total_chapters=max_n)
                print(f"  [{i}/{len(missing)}] {ch_name} ({export_format.upper()})...", flush=True)
                chapter_url = parsed_urls.get(n, f"{url.rstrip('/')}/chuong-{n}")
                success, msg = crawler.download_chapter(
                    ch_name, chapter_url, site_config, str(out_dir), export_format
                )
                if success:
                    new_count += 1
                    manifest[chapter_key(n)]["title"] = ch_name
                    manifest[chapter_key(n)]["local_name"] = ch_name
                    manifest[chapter_key(n)]["format"] = export_format
                    print(f"  [OK] {ch_name} saved", flush=True)
                else:
                    print(f"  [Failed] {ch_name}: {msg}", flush=True)
            print(f"  Downloaded {new_count} new chapter(s)", flush=True)
            save_meta(meta_path, meta)
    finally:
        crawler.close()


if __name__ == "__main__":
    main()
