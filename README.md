# ToolCrawlComic (v1.4.0)

A high-throughput, multi-threaded comic scraper and cloud synchronization pipeline for Vietnamese & international manga/manhua/manhwa websites. Features **In-Memory WebP Transcoding**, **Cloudflare R2 Storage (with 1-Year Immutable CDN Edge Caching)**, **Supabase PostgreSQL Relational Sync (with Decimal Chapter Support)**, **Google Drive CBZ Backups (`rclone`)**, **Atomic Local Pruning**, and **Rich Discord Webhook Notifications**.

---

## 🌟 Key Features

- **⚡ In-Memory WebP Transcoding & Dimension Clamping (`ImageProcessor`)**:
  - Transcodes scraped raw JPEG/PNG images inline in RAM to WebP (`quality=81`, `method=4`).
  - Automatically downscales oversized images ($\le 1,400\text{px}$) with `Image.Resampling.LANCZOS` preserving aspect ratio.
  - Strips unused alpha channels by flattening RGBA onto a clean white background.
  - Respects the WebP hard specification limit ($16,383 \times 16,383\text{px}$): automatically falls back to Progressive MozJPEG for extreme vertical webtoon strips.
  - Generates SHA-256 content hashes on raw buffers for deduplication.
  - Achieves **65%–75% storage savings**, expanding the Cloudflare R2 10GB free tier capacity to **~2,630+ chapters**.

- **☁️ Cloudflare R2 Storage & Immutable CDN Edge Caching**:
  - Thread-isolated `boto3` client instances (`_get_r2_client()`) preventing race conditions.
  - Enforces `ContentType: image/webp` and `Cache-Control: public, max-age=31536000, immutable` for 1-year Cloudflare Edge POP caching with ~99% cache hit ratios.
  - O(1) prefix pagination with strict trailing-slash delimiters preventing prefix overlap bleed.

- **🗄️ Supabase PostgreSQL Relational Metadata Core**:
  - Automatically synchronizes and links `authors`, `categories`, `genres`, `stories`, `story_genres`, and `chapters`.
  - Supports integer and decimal/bonus chapter numbers (`NUMERIC` column, e.g. Chapter 97.5, Chapter 0.5).
  - Run-scoped memoization (`_LOOKUP_CACHE`) eliminates up to 90% of redundant PostgREST lookups.
  - Execution metrics and durations recorded into `crawler_runs` (`status: succeeded`).

- **🔍 Full-Series Deep Prober (`crawl_full.py`)**:
  - Bypasses frontend website pagination and truncation limits (e.g. NetTruyen's 20-chapter view) by concurrently probing server endpoints from `Chapter 001` to the latest chapter.
  - Supports outputting directly to `.cbz` reader archives or WebP image folders.

- **💾 Google Drive Backup & Safe Pruning (`rclone`)**:
  - Mirrors comic catalogs and `.cbz` archives to `gdrive:Comic/` with `--transfers 8 --fast-list`.
  - **Pruning Safety Guardrail:** Local files in `downloads/` are strictly preserved unless both R2 upload and Google Drive backup exit with code 0.

- **🩺 Pre-Flight Diagnostics (`--health`)**:
  - 1-Command check verifying R2 bucket, Supabase database, `rclone` binary, and Discord webhook connectivity in <1s.

- **📢 Rich Discord Webhook Notifications**:
  - Embed alerts containing comic titles, authors, categories, chapter lists, and execution duration.

---

## 🚀 Installation & Setup

```powershell
pip install -r requirements.txt
cp secrets.env.template secrets.env
```

Configure your credentials in `secrets.env`:
```env
# Cloudflare R2 (S3-Compatible)
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=comic
R2_PUBLIC_URL=https://pub-xxx.r2.dev

# Discord Notifications
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Supabase PostgreSQL
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key

# Local Paths & Cloud Backup
DOWNLOADS_DIR=downloads
RCLONE_REMOTE=gdrive:Comic
```

---

## 📖 Complete End-to-End Operational Guide

### Step 1: Run Pre-Flight Diagnostics
```powershell
python sync_pipeline.py --health
```

### Step 2: Crawl Comic Chapters

#### Option A — Standard Visible Crawl & Library Track:
```powershell
# Crawl all visible chapters as WebP images
python main.py "https://nettruyen.gg/truyen-tranh/crush-cua-toi-la-mot-dua-lang-lo" -f images -o downloads

# Crawl a specific chapter range (e.g. chapters 1 to 20)
python main.py "https://nettruyen.gg/truyen-tranh/crush-cua-toi-la-mot-dua-lang-lo" --start 1 --end 20 -f images -o downloads

# Crawl and package directly as .cbz reader archives
python main.py "https://nettruyen.gg/truyen-tranh/crush-cua-toi-la-mot-dua-lang-lo" -f cbz -o downloads
```

#### Option B — Deep Full-Series Probing (Chapter 1 $\to$ Latest):
```powershell
# Deep probe and download all chapters from 1 to latest as CBZ archives
python crawl_full.py "https://nettruyen.gg/truyen-tranh/crush-cua-toi-la-mot-dua-lang-lo" -f cbz

# Deep probe and download as WebP image folders
python crawl_full.py "https://nettruyen.gg/truyen-tranh/crush-cua-toi-la-mot-dua-lang-lo" -f images
```

### Step 3: Library Management & Batch Updates
```powershell
# List all tracked favorite comics
python main.py list

# 1-Command Batch Auto-Update all tracked library comics
python main.py update -o downloads
```

### Step 4: Archive Conversion (Images $\to$ CBZ / PDF)
```powershell
# Convert local image folders to CBZ archives
python main.py convert "downloads\Crush Của Tôi Là Một Đứa Lẳng Lơ" -f cbz

# Convert local image folders to PDF documents
python main.py convert "downloads\Crush Của Tôi Là Một Đứa Lẳng Lơ" -f pdf
```

### Step 5: Cloud Synchronization & Local Prune
```powershell
# Dry Run: Simulate R2 uploads, Supabase SQL inserts & Discord embed
python sync_pipeline.py --dry-run

# Sync ONLY a specific comic to R2 & Supabase (skip others)
python sync_pipeline.py --comic "Crush Của Tôi Là Một Đứa Lẳng Lơ" --skip-backup

# Full Live Sync + Google Drive Backup + Local Safe Prune
python sync_pipeline.py --prune
```

### Step 6: Standalone Google Drive Backup (`rclone`)
```powershell
rclone copy "downloads\Crush Của Tôi Là Một Đứa Lẳng Lơ" "gdrive:Comic/Crush Của Tôi Là Một Đứa Lẳng Lơ" --transfers 8 --fast-list -v
```

### Step 7: Unattended Daily Automation
```cmd
run_daily.bat
```

---

## 📋 CLI Commands Quick Reference

| Command | Description |
|:---|:---|
| `python sync_pipeline.py --health` | Pre-flight diagnostic check verifying R2, Supabase, Drive & Discord |
| `python main.py "<URL>" -f images` | Scrape comic chapters with inline WebP optimization & track in library |
| `python main.py "<URL>" -f cbz` | Scrape comic and pack directly into `.cbz` reader archives |
| `python main.py update -o downloads` | 1-Command batch update all tracked library favorites |
| `python main.py list` | Display all tracked comics with last sync timestamps |
| `python crawl_full.py "<URL>" -f cbz` | Deep probe & download full series (Chapter 1 $\to$ Latest) as CBZ |
| `python crawl_full.py "<URL>" -f images` | Deep probe & download full series (Chapter 1 $\to$ Latest) as WebP images |
| `python main.py convert "<PATH>" -f cbz` | Convert downloaded image directory to `.cbz` files |
| `python sync_pipeline.py --dry-run` | Safe simulation of R2 upload, DB sync, and Discord report |
| `python sync_pipeline.py --comic "<NAME>"` | Target sync and upload for a specific comic |
| `python sync_pipeline.py --prune` | Live sync to R2 & Supabase, backup to Google Drive, and prune local files |
| `python -m unittest discover -s . -p "test_*.py"` | Run the 41-test automated unit test suite |
| `run_daily.bat` | Windows batch runner for automated daily unattended runs |

---

## 🏗️ Architecture & Decision Records

Detailed engineering rationales are documented in Architecture Decision Records:
- [ADR-001: Cloud Sync Pipeline Architecture](docs/decisions/ADR-001-cloud-sync-pipeline-architecture.md)
- [ADR-002: Relational Metadata & Junction Tables](docs/decisions/ADR-002-relational-metadata-and-junction-tables.md)
- [ADR-003: Deprecation & Schema Migration Strategy](docs/decisions/ADR-003-deprecation-and-schema-migration-strategy.md)
- [ADR-004: Concurrency Safety & HTTP Connection Pooling](docs/decisions/ADR-004-concurrency-safety-and-http-connection-pooling.md)
- [ADR-005: Inline WebP Compression & Cloudflare Edge POP Caching](docs/decisions/ADR-005-inline-webp-compression-and-cdn-caching.md)

---

## 🧪 Automated Quality Gates

Every commit is verified against an automated unit test suite (**41 / 41 passing**):
- `test_image_processor.py`: In-memory WebP transcoding, dimension clamping, alpha flattening, MozJPEG 16383px fallback, color modes (Grayscale `L`, Bilevel `1`, Palette `P`, CMYK).
- `test_chapter_namer.py`: Standard, decimal, prequel (`Chapter 0`), and Vietnamese chapter extraction (`Tập 2 Chương 45`).
- `test_sync_pipeline.py`: S3 prefix isolation, PostgREST pagination, immutable CDN caching headers, Discord webhook payloads, `--health` diagnostics.
- `test_crawler.py`: HTML selector extraction, blacklist filtering, relative URL resolution.
- `test_converter.py`: In-memory CBZ and PDF packing.
- `test_library.py`: Atomic `.tmp` file replacement and schema version fallback.
- `test_crawl_full.py`: Concurrent chapter probing and gap filling.
