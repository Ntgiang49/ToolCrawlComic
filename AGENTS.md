# AGENTS.md: Antigravity & Agentic Pair Programming Guide

## Project Overview
**ToolCrawlComic (v1.4.0)**: High-throughput, multi-threaded comic scraper and cloud synchronization pipeline for Vietnamese & international manga/manhua/manhwa websites. Transcodes pages inline to WebP, uploads to Cloudflare R2 with immutable edge caching, syncs relational metadata to Supabase PostgreSQL, backs up to Google Drive via `rclone`, and reports execution metrics to Discord.

---

## Tech Stack
- **Language & Runtime:** Python 3.11, 3.12, 3.13 (cross-platform, Windows/Linux)
- **Scraping & HTML Parsing:** `requests`, `requests.adapters.HTTPAdapter`, `beautifulsoup4`, `lxml`
- **Image Processing Engine:** `Pillow` (native libwebp C-bindings)
- **Cloud Storage:** Cloudflare R2 (`boto3` S3-compatible client)
- **Database:** Supabase PostgreSQL via PostgREST REST API
- **Cloud Backup & Pruning:** `rclone` (Google Drive `gdrive:Comic`)
- **CLI & Monitoring:** `tqdm` (thread-safe progress bars), Discord Webhooks

---

## Commands Reference

### Testing & Quality Gates
- **Run Entire Test Suite (41 tests):**
  ```powershell
  python -m unittest discover -s . -p "test_*.py"
  ```
- **Pre-Flight Health Diagnostics:**
  ```powershell
  python sync_pipeline.py --health
  ```
- **Run Single Focused Test:**
  ```powershell
  python -m unittest test_image_processor.py
  python -m unittest test_sync_pipeline.py
  ```

### Crawler & Pipeline Operations
- **Crawl & Track a Comic:**
  ```powershell
  python main.py "https://nettruyen.gg/truyen-tranh/su-tro-lai-cua-quyen-vuong" -f images -o downloads
  ```
- **Deep Full-Series Probe (Chapter 1 -> Latest) as CBZ:**
  ```powershell
  python crawl_full.py "https://nettruyen.gg/truyen-tranh/crush-cua-toi-la-mot-dua-lang-lo" -f cbz
  ```
- **1-Command Batch Update All Library Favorites:**
  ```powershell
  python main.py update -o downloads
  ```
- **List Tracked Library Comics:**
  ```powershell
  python main.py list
  ```
- **Convert Local Image Folder to CBZ:**
  ```powershell
  python main.py convert "downloads\Comic Name" -f cbz
  ```
- **Cloud Sync Dry Run (Safe Test):**
  ```powershell
  python sync_pipeline.py --dry-run
  ```
- **Single Comic Cloud Sync:**
  ```powershell
  python sync_pipeline.py --comic "Comic Name" --skip-backup
  ```
- **Live Cloud Sync, Drive Backup & Local Prune:**
  ```powershell
  python sync_pipeline.py --prune
  ```
- **Daily Unattended Windows Batch Run:**
  ```cmd
  run_daily.bat
  ```

---

## Architecture & Code Conventions

### 1. In-Memory Image Processing (`comic_crawler/image_processor.py`)
- Always transcode scraped raw images inline to WebP (`quality=81`, `method=4`).
- Always clamp max width to $\le 1,400\text{px}$ using `Image.Resampling.LANCZOS` preserving aspect ratio.
- Strip unused alpha channels by flattening RGBA onto a clean white RGB background.
- Respect the WebP hard specification limit ($16,383 \times 16,383\text{px}$): if height or width exceeds 16,383px, fallback to Progressive MozJPEG (`quality=82`).
- Compute SHA-256 content hashes on raw buffers for deduplication.

### 2. Thread Safety & Cloudflare R2 Uploads (`sync_pipeline.py`)
- Never share a global `boto3.client` across threads. Use `_get_r2_client()` which utilizes `threading.local()` isolation.
- Always attach immutable CDN cache headers to R2 PutObject commands:
  ```python
  ExtraArgs = {
      "ContentType": "image/webp",
      "CacheControl": "public, max-age=31536000, immutable",
      "ContentDisposition": "inline",
  }
  ```
- Always enforce trailing slashes (`prefix/`) in `get_existing_r2_keys` to prevent S3 prefix overlap bleed (e.g. `ch_1/` vs `ch_10/`).

### 3. Atomic Database & Library Writes (`comic_crawler/library.py`)
- Never write directly to `library.json`. Always write to `library.json.tmp` and atomic replace with `os.replace` to prevent corruption during unexpected shutdowns.

### 4. Relational Database Sync (`sync_pipeline.py` & Supabase)
- Database tables: `authors`, `categories`, `genres`, `stories`, `story_genres`, `chapters`, `crawler_sources`, `crawler_runs`.
- `crawler_sources`: `source_type` check constraint accepts `['rss', 'api', 'html', 'manual']` (default: `'html'`).
- `crawler_runs`: `status` check constraint accepts `['queued', 'running', 'succeeded', 'failed']` (default: `'succeeded'`).

### 5. Safe Pruning Guardrails
- Local folders in `downloads/` must NEVER be pruned unless:
  1. `upload_to_r2` returned `True` for all chapter images.
  2. `backup_to_drive` returned `True` (`rclone copy` exit code `0`).

---

## Boundaries & Safety Rules
- **NEVER** commit `secrets.env` or plaintext API keys to Git history.
- **NEVER** disable tests or skip assertions to force a passing test run.
- Keep Git commit messages strictly adhering to Conventional Commits:
  - `feat(...)`, `fix(...)`, `chore(...)`, `docs(...)`, `test(...)`, `refactor(...)`.
- Update Architecture Decision Records in `docs/decisions/` whenever making significant architectural shifts.

---

## Project Directory Map
```
Tool_crawl_comic/
├── comic_crawler/              # Core Scraper Library
│   ├── core.py                 # ComicCrawler engine & HTML extraction
│   ├── image_processor.py      # WebP transcoding & dimension clamping
│   ├── library.py              # Atomic library.json tracking manager
│   ├── chapter_namer.py        # Numerical chapter naming & regex parser
│   ├── exporter.py             # CBZ & PDF conversion utilities
│   ├── config_loader.py        # Multi-domain CSS selector loader
│   └── utils.py                # Filename sanitization & URL resolution
├── sync_pipeline.py            # R2, Supabase, Drive & Discord orchestrator
├── main.py                     # Interactive & CLI entrypoint
├── crawl_full.py               # Deep chapter probing & gap filler
├── run_daily.bat               # Windows daily automation batch script
├── config.json                 # Domain selector configurations & blacklists
├── library.json                # Tracked favorite comics catalog
├── secrets.env.template        # Environment variable template
├── docs/                       # Architectural records (ADR-001 - ADR-005)
└── test_*.py                   # 41-test automated unit test suite
```
