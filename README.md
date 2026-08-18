# Comic Crawler Easy & Cloud Sync Pipeline

A fast, lightweight, modular Python comic crawler and cloud sync pipeline featuring **Incremental Crawling**, **Cloudflare R2 Image Hosting (Live Progress)**, **Supabase Relational Core Sync**, **Google Drive Backups (rclone)**, **Atomic Local Pruning**, and **Rich Discord Webhook Notifications**.

---

## 🌟 Key Features

- **Automated Daily Sync Pipeline (`python sync_pipeline.py --prune`)**:
  - **Live CLI Upload Progress**: `tqdm` byte progress bar for chapter uploads.
  - **R2 Fast Sync**: Uses `list_objects_v2` for O(1) existence checks.
  - **Supabase Core Sync**: Upserts `authors`, `categories`, `genres`, `story_genres`, and logs metrics to `crawler_runs`.
  - **Google Drive Backup**: Automatic `rclone copy` to cloud backup.
  - **Safe Local Pruning**: Deletes local chapter directories only after R2 + Drive confirmation.
  - **Rich Discord Alerts**: Embeds with comic title, author, category, chapter list, and totals.
- **1-Command Batch Auto-Update (`python main.py update`)**:
  - Incremental sync: checks local files and skips existing chapters without re-downloading.
- **Single URL Crawl (`python main.py <URL>`)**:
  - Downloads all chapters and automatically tracks in `library.json` and writes `meta.json`.
- **Local Folder Converter (`python main.py convert <PATH>`)**:
  - Converts downloaded image folders into `.cbz` or `.pdf` comic archives.
- **Zero-Padded Chapter Naming**:
  - Formats chapters chronologically (e.g., `Chapter 001.cbz`, `Chapter 012.5.cbz`).

---

## 🚀 Installation & Setup

```bash
pip install -r requirements.txt
cp secrets.env.template secrets.env
```

Configure your credentials in `secrets.env`:
```env
# Cloudflare R2
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=comic
R2_PUBLIC_URL=https://pub-xxx.r2.dev

# Discord Notification
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Supabase REST
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_service_role_key

# Paths & Backup
DOWNLOADS_DIR=downloads
RCLONE_REMOTE=gdrive:Comic
```

---

## 📖 CLI Commands

| Command | Description |
|---|---|
| `python main.py <URL>` | Download comic & track in library |
| `python main.py update` | Batch update all tracked comics |
| `python sync_pipeline.py --dry-run` | Test sync pipeline without writes |
| `python sync_pipeline.py --prune` | Upload to R2, sync Supabase, backup Drive & prune local |
| `python main.py convert <PATH> --format cbz` | Convert folder to CBZ |
| `python -m unittest discover -s . -p "test_*.py"` | Run full test suite (22 tests) |
| `run_daily.bat` | Windows batch runner for daily cron |

---

## 🏗️ Architecture & Decisions

Detailed design rationales are recorded in Architecture Decision Records:
- [ADR-001: Cloud Sync Pipeline Architecture](file:///docs/decisions/ADR-001-cloud-sync-pipeline-architecture.md)
- [ADR-002: Relational Metadata & Junction Tables](file:///docs/decisions/ADR-002-relational-metadata-and-junction-tables.md)
