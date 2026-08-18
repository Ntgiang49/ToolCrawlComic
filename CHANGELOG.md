# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
