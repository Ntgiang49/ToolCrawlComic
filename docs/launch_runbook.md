# Production Shipping & Launch Runbook

## 1. System Overview
The Comic Crawler & Cloud Sync Pipeline is ready for production daily automated execution.

- **Crawler Core**: Crawls comics and chapters, extracting full metadata (`url`, `title`, `author`, `category`, `description`).
- **Cloud Sync Pipeline**: Multi-threaded R2 upload (with `tqdm`), Supabase relational upsert (`authors`, `categories`, `genres`, `story_genres`, `chapters`, `crawler_runs`), Google Drive backup via `rclone`, atomic local prune, and rich Discord notifications.

---

## 2. Pre-Launch Gate Checklist

- [x] **Unit & Integration Tests**: 22/22 tests passing in 0.3s (`python -m unittest discover -s . -p "test_*.py"`).
- [x] **Dry-Run Validation**: Verified zero-error execution in `--dry-run` and `--skip-backup` modes.
- [x] **Database Migrations**: `create_story_genres_and_tags` applied with RLS & public select policies.
- [x] **Security & Secrets**: No secrets in source code; template configured at [`secrets.env.template`](file:///D:/01_Projects/Tool_crawl_comic/secrets.env.template).
- [x] **Zero-Loss Auto-Prune**: Verified local files only delete after successful R2 upload and Drive backup.
- [x] **Documentation & ADRs**: [`README.md`](file:///D:/01_Projects/Tool_crawl_comic/README.md), [`ADR-001`](file:///D:/01_Projects/Tool_crawl_comic/docs/decisions/ADR-001-cloud-sync-pipeline-architecture.md), [`ADR-002`](file:///D:/01_Projects/Tool_crawl_comic/docs/decisions/ADR-002-relational-metadata-and-junction-tables.md).

---

## 3. Production Launch & Execution Steps

### Step 1: Configure Environment
Ensure `secrets.env` is populated in the root directory:
```env
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=comic
R2_PUBLIC_URL=https://pub-006586cb2a0d4198bcd302b9b8f8ea45.r2.dev
DISCORD_WEBHOOK_URL=...
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
DOWNLOADS_DIR=D:\light-story
RCLONE_REMOTE=gdrive:Comic
```

### Step 2: Test Run
```bash
python sync_pipeline.py --dry-run
```

### Step 3: Run Full Pipeline (Live)
```bash
# Windows Daily Batch Run (Crawl -> Sync -> Backup -> Prune -> Discord)
run_daily.bat
```
*Or directly in Python:*
```bash
python sync_pipeline.py --prune
```

---

## 4. Rollback & Contingency Plan

### Trigger Conditions
- R2 503 throttling or authentication errors.
- Database write failure or connection loss.
- Unexpected file deletion without backup confirmation.

### Rollback Steps
1. **Disable Auto-Prune**: Remove `--prune` flag from `run_daily.bat`. Local downloads will be retained on disk.
2. **Skip Drive Backup**: Pass `--skip-backup` if rclone network is unavailable.
3. **Revert Pipeline Code**: `git checkout main` (or previous commit).
4. **Database Rollback**:
   ```sql
   DROP TABLE IF EXISTS public.story_tags CASCADE;
   DROP TABLE IF EXISTS public.story_genres CASCADE;
   ```
