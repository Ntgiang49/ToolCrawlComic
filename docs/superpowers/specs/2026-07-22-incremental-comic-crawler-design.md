# Design Specification: Integrated Library Manager & Incremental Auto-Sync

**Target Directory**: `d:\Tool_crawl_comic`  
**Date**: 2026-07-22  
**Status**: Approved / In Spec Review  

---

## 1. Overview & Goals

Enhance the Comic Crawler tool to support effortless 1-command crawling, auto-tracking of favorite comics in a central `library.json`, smart local chapter incremental syncing (skipping already downloaded chapters), and standardized zero-padded chapter file naming (`Chapter 001.cbz`, `Chapter 012.5.cbz`).

---

## 2. Architecture & Components

```
d:\Tool_crawl_comic\
├── library.json                 # Tracked comics database (auto-managed JSON)
├── config.json                  # Site rules & CSS selectors
├── main.py                      # CLI & single-command entry point
├── comic_crawler/
│   ├── library.py               # NEW: Library management (add, list, remove, load, save)
│   ├── chapter_namer.py         # NEW: Zero-padded chapter name formatter & number parser
│   ├── core.py                  # UPDATED: Incremental chapter skipping & sync core
│   ├── exporter.py              # Export engine (CBZ, PDF, Images)
│   └── utils.py                 # Utility helpers
```

---

## 3. Detailed Component Designs

### 3.1 `library.py` (Library Manager)
- Manages `library.json` storing subscriptions:
  ```json
  {
    "comics": {
      "https://example.com/manga/solo-leveling": {
        "title": "Solo Leveling",
        "url": "https://example.com/manga/solo-leveling",
        "format": "cbz",
        "threads": 8,
        "last_downloaded": "2026-07-22 15:30",
        "downloaded_chapters": ["Chapter 001", "Chapter 002"]
      }
    }
  }
  ```
- Functions: `add_or_update_comic()`, `get_all_tracked()`, `remove_comic()`.

### 3.2 `chapter_namer.py` (Zero-Padded Naming & Number Parsing)
- Extracts chapter numbers from raw site titles (e.g., `"Read Chapter 12.5 Online"` -> `12.5`, `"Ch. 100"` -> `100`).
- Pads chapter numbers automatically based on total count or standard 3-digit minimum (e.g. `001`, `002`, `010.5`, `100`).
- Generates clean filenames: `Chapter 001.cbz`, `Chapter 012.5.pdf`.

### 3.3 Incremental Sync Engine in `core.py`
- Before attempting HTML fetching or downloading images for a chapter:
  1. Computes expected target filename in `downloads/<Comic Title>/` (e.g. `downloads/Solo Leveling/Chapter 001.cbz`).
  2. Checks if `Chapter 001.cbz` (or corresponding `.pdf` / folder) already exists locally and has non-zero size.
  3. If exists: **SKIPS** chapter immediately with notice: `[Skipped] Chapter 001 (already downloaded)`.
  4. If missing: Downloads chapter images and exports output.

### 3.4 CLI & Command Commands (`main.py`)
- **Single URL execution**:
  ```powershell
  python main.py "https://example.com/manga/title"
  ```
  Auto-detects title, saves/updates to `library.json`, downloads all missing chapters.

- **Batch 1-Command Auto-Update**:
  ```powershell
  python main.py update
  ```
  Loops through all subscribed comics in `library.json`, checks for newly released chapters, and downloads only new ones.

- **List Tracked Comics**:
  ```powershell
  python main.py list
  ```

---

## 4. Verification & Testing Plan

1. **Unit Tests (`test_crawler.py`)**:
   - Test chapter number parser and zero-padding logic (`1` -> `001`, `12.5` -> `012.5`).
   - Test `library.json` loading and saving.
   - Test incremental skipping when dummy files exist.
2. **End-to-End Test**:
   - Run `python main.py update` to verify batch processing logic.
