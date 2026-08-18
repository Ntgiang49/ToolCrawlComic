import argparse
import sys
import os
import io
import json

# Force UTF-8 encoding for stdout/stderr to support Vietnamese & unicode comic titles safely
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from comic_crawler.core import ComicCrawler
from comic_crawler.library import LibraryManager
from comic_crawler.exporter import ComicExporter

BANNER = r"""
=====================================================
       ___                    _       ____                      
      / _ \ _  _ _  _ _  ____| |_    / ___| _  _ ___ ____  ____ 
     | |_| | || | || | |/ / _` | |_  | |__| || / _ \  _ \/ __/ 
     |  _  | || | || | ' < (_| | | |_| |__| || \ __/ |_| \__ \ 
     |_| |_|\_,_|\_,_|_|\_\__,_|_|\__\____|\_,_|\___| .__/___/ 
                                                    |_|         
                     COMIC CRAWLER EASY v1.3
=====================================================
"""

def sync_single_comic(crawler: ComicCrawler, library: LibraryManager, url: str, export_format: str, output_base: str, start: int = None, end: int = None):
    print(f"\n[Parsing] Fetching info from: {url}")
    try:
        info = crawler.parse_comic_info(url)
    except Exception as e:
        print(f"[Error] Failed to parse comic page ({url}): {e}")
        return

    title = info["title"]
    chapters = info["chapters"]
    out_dir = os.path.join(output_base, title)
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({
            "url": url,
            "title": title,
            "author": info.get("author", "Unknown"),
            "category": info.get("category", "Unknown"),
            "description": info.get("description", "")
        }, f, ensure_ascii=False, indent=2)

    # Save/Update comic in library.json tracker
    library.add_or_update_comic(
        url=url, 
        title=title, 
        export_format=export_format, 
        threads=crawler.num_threads, 
        total_chapters=len(chapters)
    )

    if not chapters:
        print("[Notice] Could not auto-detect chapter list. Attempting single page download...")
        success, msg = crawler.download_chapter("Chapter 001", url, info["site_config"], out_dir, export_format)
        print(f"  -> {msg}")
        return

    # Filter chapter range if specified
    start_idx = max(1, start) if start else 1
    end_idx = min(len(chapters), end) if end else len(chapters)
    target_chapters = chapters[start_idx - 1 : end_idx]

    print(f"\nComic: '{title}' | Found {len(chapters)} total chapters | Syncing {len(target_chapters)} chapters -> '{out_dir}' ({export_format.upper()})")

    downloaded_count = 0
    skipped_count = 0

    for idx, ch in enumerate(target_chapters, 1):
        ch_title = ch["title"]
        ch_url = ch["url"]
        
        success, msg = crawler.download_chapter(ch_title, ch_url, info["site_config"], out_dir, export_format)
        if success:
            if "[Skipped]" in msg:
                skipped_count += 1
            else:
                downloaded_count += 1
                print(f"  [{idx}/{len(target_chapters)}] {msg}")
        else:
            print(f"  [{idx}/{len(target_chapters)}] [Failed] {ch_title}: {msg}")

    print(f"[Summary] '{title}': {downloaded_count} new downloaded, {skipped_count} existing skipped.")

def update_all_library(crawler_factory, library: LibraryManager, output_base: str):
    all_comics = library.get_all_comics()
    if not all_comics:
        print("\n[Library] No tracked comics found in library.json.")
        print("To track a comic, simply run: python main.py <COMIC_URL>")
        return

    print(f"\n=====================================================")
    print(f"Starting 1-Command Batch Auto-Update ({len(all_comics)} comics in library)")
    print(f"=====================================================")

    for idx, (url, item) in enumerate(all_comics.items(), 1):
        print(f"\n[{idx}/{len(all_comics)}] Syncing favorite: {item.get('title', url)}")
        fmt = item.get("format", "cbz")
        threads = item.get("threads", 8)
        crawler = crawler_factory(threads)
        sync_single_comic(crawler, library, url, fmt, output_base)

    print(f"\n=====================================================")
    print("All library comics are up-to-date!")
    print(f"=====================================================")

def list_tracked_comics(library: LibraryManager):
    all_comics = library.get_all_comics()
    print("\n=====================================================")
    print(f"Tracked Comics Library ({len(all_comics)} items)")
    print("=====================================================")
    if not all_comics:
        print("No comics tracked yet. Run 'python main.py <URL>' to add a comic.")
    else:
        for idx, (url, item) in enumerate(all_comics.items(), 1):
            print(f"{idx}. {item.get('title', 'Unknown')} [{item.get('format', 'cbz').upper()}]")
            print(f"   URL: {url}")
            print(f"   Last Synced: {item.get('last_synced', 'Never')}")
            print()

def convert_folder(folder_path: str, target_format: str = "cbz"):
    print(f"\n[Convert] Scanning directory: '{folder_path}' -> Target Format: {target_format.upper()}")
    try:
        results = ComicExporter.convert_directory(folder_path, target_format)
        print(f"[Success] Converted {len(results)} item(s):")
        for res in results:
            print(f"  -> {os.path.basename(res)}")
    except Exception as e:
        print(f"[Error] Conversion failed: {e}")

def interactive_mode(library: LibraryManager):
    print(BANNER)
    print("Select Action:")
    print("  1. Download / Track a Comic URL")
    print("  2. Sync All Tracked Favorites (1-Command Update)")
    print("  3. List Tracked Comics")
    print("  4. Convert Local Image Folder to CBZ / PDF")
    print("  5. Exit")
    choice = input("Choice (1-5) [default 1]: ").strip()

    if choice == "2":
        update_all_library(lambda t: ComicCrawler(num_threads=t), library, "downloads")
        return
    elif choice == "3":
        list_tracked_comics(library)
        return
    elif choice == "4":
        dir_path = input("Enter path to local comic folder: ").strip()
        if os.path.exists(dir_path):
            fmt = input("Format (1: CBZ, 2: PDF) [default 1]: ").strip()
            target_fmt = "pdf" if fmt == "2" else "cbz"
            convert_folder(dir_path, target_fmt)
        else:
            print("[Error] Folder path does not exist.")
        return
    elif choice == "5":
        sys.exit(0)

    url = input("\nEnter Comic URL: ").strip()
    if not url:
        print("[Error] No URL provided. Exiting.")
        sys.exit(1)

    threads_input = input("Download Threads [default 8]: ").strip()
    threads = int(threads_input) if threads_input.isdigit() else 8

    print("\nSelect Export Format:")
    print("  1. CBZ (Comic Book Zip - Recommended)")
    print("  2. PDF Document")
    print("  3. Raw Image Folders")
    fmt_choice = input("Choice (1-3) [default 1]: ").strip()

    fmt_map = {"1": "cbz", "2": "pdf", "3": "images"}
    export_format = fmt_map.get(fmt_choice, "cbz")

    crawler = ComicCrawler(num_threads=threads)
    sync_single_comic(crawler, library, url, export_format, "downloads")

def main():
    parser = argparse.ArgumentParser(
        description="Comic Crawler Easy - Crawl comics into CBZ/PDF/Images with auto-sync"
    )
    parser.add_argument("command_or_url", nargs="?", help="Comic URL OR command ('update', 'list', 'convert', 'remove')")
    parser.add_argument("extra_arg", nargs="?", help="Path for convert command OR URL for remove command")
    parser.add_argument("-f", "--format", choices=["cbz", "pdf", "images"], default="cbz", help="Output format")
    parser.add_argument("-t", "--threads", type=int, default=8, help="Number of download threads")
    parser.add_argument("-o", "--output", type=str, default="downloads", help="Output directory path")
    parser.add_argument("--start", type=int, help="Start chapter index")
    parser.add_argument("--end", type=int, help="End chapter index")
    parser.add_argument("-c", "--config", type=str, default="config.json", help="Site config JSON path")
    parser.add_argument("-l", "--library", type=str, default="library.json", help="Library database JSON path")

    args = parser.parse_args()
    library = LibraryManager(args.library)

    cmd = args.command_or_url

    if not cmd:
        interactive_mode(library)
    elif cmd.lower() == "update":
        update_all_library(lambda t: ComicCrawler(config_path=args.config, num_threads=t), library, args.output)
    elif cmd.lower() == "list":
        list_tracked_comics(library)
    elif cmd.lower() == "remove":
        target_url = args.extra_arg
        if target_url and library.remove_comic(target_url):
            print(f"[Success] Removed '{target_url}' from library.")
        else:
            print(f"[Error] URL not found in library: '{target_url}'")
    elif cmd.lower() == "convert":
        target_path = args.extra_arg
        if target_path and os.path.exists(target_path):
            convert_folder(target_path, args.format)
        else:
            print("[Error] Please specify a valid folder path: python main.py convert <FOLDER_PATH> --format cbz")
    elif cmd.startswith(("http://", "https://")):
        crawler = ComicCrawler(config_path=args.config, num_threads=args.threads)
        sync_single_comic(crawler, library, cmd, args.format, args.output, args.start, args.end)
    else:
        print(f"[Error] Unknown command or invalid URL: '{cmd}'")
        print("Usage Commands:")
        print("  python main.py <URL>                      # Download & track a comic")
        print("  python main.py update                     # Update all tracked comics")
        print("  python main.py list                       # View tracked library")
        print("  python main.py remove <URL>               # Remove comic from library")
        print("  python main.py convert <PATH> -f cbz|pdf  # Convert local folder to CBZ/PDF")

if __name__ == "__main__":
    main()
