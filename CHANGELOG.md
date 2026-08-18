# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] - 2026-08-18

### Added
- **In-Memory ImageProcessor Engine (`comic_crawler/image_processor.py`)**: Real-time transcoding of scanned pages to WebP ($Q=81$, method=4) in RAM before disk writing or CBZ packing, achieving 65%–75% file size reduction.
- **Dynamic Dimension Clamping**: Automatic downscaling of oversized 3K/4K scans to $\le 1,400\text{px}$ width using Lanczos resampling.
- **WebP 16,383px Dimension Guard**: Automatic fallback to Progressive MozJPEG for extreme vertical webtoon strips exceeding WebP's hard limit.
- **Alpha Channel Flattening**: Stripping unused transparency channels from scanned pages by flattening onto a clean white background.
- **1-Year Immutable CDN Caching**: Attached `Cache-Control: public, max-age=31536000, immutable` and `Content-Type: image/webp` to all Cloudflare R2 uploads to maximize edge POP caching.
- **ADR-005**: Documented architecture decisions for inline WebP optimization and CDN cache strategy.
- **Extended Test Suite**: Added 7 new unit tests for image transcoding, corruption rejection, alpha flattening, and S3 metadata headers (36 total tests).

## [1.3.0] - 2026-08-18

### Fixed
- **Pipeline Crash in `crawl_full.py`**: Added missing `ThreadPoolExecutor` import.
- **Data Pollution from Navigation Links**: Implemented `chapter_title_blacklist` in parser and config to prevent downloading navigation buttons ("Đọc mới nhất", "Đọc từ đầu", "Xem thêm") as chapters.
- **Decimal Chapter Collisions**: Updated chapter number parsing and database queries to support float chapters (e.g. Chapter 012.5) without truncating to integer.
- **Silent Database Corruption Risk**: Implemented atomic writes (`.tmp` + `os.replace`) for `library.json`.

### Added
- **Thread-Safe R2 Uploads**: Implemented thread-local `boto3` S3 client isolation to prevent connection concurrency drops under load.
- **R2 Continuation Pagination**: Implemented pagination support in `get_existing_r2_keys` for bucket prefixes with >1,000 objects.
- **In-Memory Supabase Lookup Caching**: Added run-scoped caching for author, category, and genre lookups, eliminating up to 90% of redundant REST API calls.
- **HTTP Connection Pool Scaling**: Mounted `requests.adapters.HTTPAdapter` configured to match worker thread concurrency.
- **Automated Log Rotation**: Added size-based rotation (>5MB) in `run_daily.bat` to prevent unbounded log growth.
- **Configurable Chapter Ordering**: Added `chapter_order` (`desc`/`asc`) to site configuration.
- **GIF Image Support**: Added `.gif` to valid formats in `ComicExporter`.
- **Extended Test Suite**: Added 5 new unit tests (27 total) covering pagination, context management, blacklist filtering, and `crawl_full.py`.

### Changed
- **Optimized Deduplication**: Converted chapter link collection to $O(1)$ set lookup.
- **Refactored Exporter**: Extracted `_export_to_target` helper to eliminate duplicate export branch handling.
- **Code Cleanups**: Removed unused imports across modules.

## [1.1.0] - 2026-08-18

### Added
- **Extended Metadata Scraping**: Scrapes `author`, `category`, and `description` across all 8 supported comic domains with automated prefix cleaning.
- **Relational Supabase Synchronization**: Auto-provisions and links `authors`, `categories`, `genres`, and `story_genres` (join table) alongside `crawler_runs` execution logging.
- **Live R2 Upload Meter**: Visual `tqdm` byte progress bar with real-time transfer throughput.
- **Google Drive Cloud Backup**: Automated `rclone copy` integration with `--fast-list` and 8 concurrent streams.
- **Safe Local Prune**: Atomic deletion of local chapter directories only upon verified R2 + Drive synchronization.
- **Rich Discord Notifications**: Formatted embeds with comic metadata, author attribution, genres, chapter list, and totals.
- **Comprehensive Unit Testing**: Added 22 unit tests covering crawler metadata, fallback selectors, Supabase helpers, prune safety, and Discord formatting.
- **Architecture Documentation**: Added `ADR-001` (Cloud Sync Pipeline) and `ADR-002` (Relational Metadata).

### Changed
- **Optimized Network Performance**: Replaced N+1 serial R2 HEAD checks with batch `list_objects_v2` and batched Supabase chapter existence lookups.
- **Concurrent Chapter Probing**: Enhanced `crawl_full.py` with `ThreadPoolExecutor(16)` for chapter enumeration.
- **Streamlined Daily Batch Runner**: Updated `run_daily.bat` to orchestrate full crawl, sync, backup, and prune in one unified workflow.

### Removed
- Untracked cached binaries and downloaded `.cbz` assets from git repository index.
