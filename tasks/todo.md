# Todo: Comic Crawler Pipeline

## Phase 1: Metadata Scraping + Supabase

- [x] **Task 1:** Scrape category/description + add selectors for all sites
  - Files: `core.py`, `config.json`, `main.py`, `crawl_full.py`
  - Scope: Medium (4 files)

- [x] **Task 2:** Supabase metadata upsert — authors, categories, stories
  - Files: `sync_pipeline.py`
  - Scope: Small (1 file)
  - Depends: Task 1

### Checkpoint: Phase 1
- [x] `meta.json` has author + category + description
- [x] Supabase `authors`/`categories` tables populated
- [x] `stories` has correct FK links
- [x] No regressions

---

## Phase 2: Upload Progress + Backup + Prune

- [x] **Task 3:** R2 upload with live CLI progress (tqdm)
  - Files: `sync_pipeline.py`
  - Scope: Small (1 file)
  - Depends: None (parallel-safe)

- [x] **Task 4:** Integrate rclone Drive backup into pipeline
  - Files: `sync_pipeline.py`, `run_daily.bat`, `secrets.env.template`
  - Scope: Small (3 files)
  - Depends: None

- [x] **Task 5:** Auto-prune local after R2 + Drive confirmed
  - Files: `sync_pipeline.py`
  - Scope: Small (1 file)
  - Depends: Task 4

### Checkpoint: Phase 2
- [x] R2 upload shows live progress bar
- [x] Drive backup runs in pipeline
- [x] `--prune` works with `--dry-run`
- [x] `run_daily.bat` still works

---

## Phase 3: Discord Notification

- [x] **Task 6:** Rich Discord embed with comic/author/chapter details
  - Files: `sync_pipeline.py`
  - Scope: Small (1 file)
  - Depends: Task 1

### Checkpoint: Complete
- [x] All acceptance criteria met
- [x] Full pipeline: crawl -> sync -> backup -> notify
- [x] Ready for daily use
