# Implementation Plan: Comic Crawler Pipeline Completion

## Overview

Fix and complete the sync pipeline: scrape full comic metadata (author, category, description) → save to `meta.json` → upload to R2 with live CLI progress → backup to Drive via rclone → auto-prune local → upsert metadata to Supabase (`authors`, `categories` tables + FK links) → send rich Discord notification.

## Architecture Decisions

- **No new dependencies.** `tqdm` already installed → reuse for R2 upload progress. `subprocess` for rclone. `boto3` callback for upload tracking.
- **Rclone stays external.** Call via `subprocess.run()` — already configured on user's machine, no Python wrapper needed.
- **Prune is opt-in.** Add `--prune` flag to `sync_pipeline.py` — destructive action needs explicit consent.
- **Category selectors are best-effort.** Each site structures genre/category differently. Scrape what's available, fallback to "Unknown".
- **`meta.json` is the bridge.** Crawler writes it, sync pipeline reads it. No direct coupling between crawler and Supabase.

## Dependency Graph

```
config.json (selectors)
    │
    ├── core.py (scrape author + category + description)
    │       │
    │       └── main.py / crawl_full.py (save extended meta.json)
    │
    └── sync_pipeline.py
            │
            ├── Task 2: Supabase upsert (authors, categories, stories)
            ├── Task 3: R2 upload with tqdm progress
            ├── Task 4: rclone Drive backup
            ├── Task 5: auto-prune after confirm
            └── Task 6: rich Discord embed
```

## Task List

### Phase 1: Metadata Scraping + Supabase

---

#### Task 1: Scrape category/description + add selectors for all sites

**Description:** Extend `parse_comic_info()` in `core.py` to also scrape category/genre and description. Add `author`, `category`, `description` selectors to all 8 site configs in `config.json`. Update `meta.json` writes in `main.py` and `crawl_full.py` to include new fields.

**Acceptance criteria:**
- [ ] `parse_comic_info()` returns `author`, `category`, `description` keys
- [ ] All 8 site configs in `config.json` have `author`, `category`, `description` selectors (best-effort per site)
- [ ] `meta.json` saved with: `url`, `title`, `author`, `category`, `description`

**Verification:**
- [ ] Run `python main.py <NETTRUYEN_URL> --end 1` → check `meta.json` has author + category + description
- [ ] Manual: inspect `meta.json` output for a known comic

**Dependencies:** None

**Files likely touched:**
- `comic_crawler/core.py` (add category + description scraping)
- `config.json` (add selectors for all sites)
- `main.py` (extend `meta.json` write at L43-44)
- `crawl_full.py` (extend `meta.json` write at L65-68)

**Estimated scope:** Medium (4 files)

---

#### Task 2: Supabase metadata upsert — authors, categories, stories

**Description:** In `sync_pipeline.py`, when creating/updating a story: get-or-create an `authors` row → set `author_id` on story. Get-or-create a `categories` row → set `category_id`. Set `description` from `meta.json`. Update `get_or_create_story()` to accept and upsert all metadata fields.

**Acceptance criteria:**
- [ ] `authors` table gets a new row if author name doesn't exist, reuses existing if it does
- [ ] `stories.author_id` FK set correctly
- [ ] `categories` table gets a new row if category doesn't exist, reuses existing if it does
- [ ] `stories.category_id` FK set correctly
- [ ] `stories.description` populated from `meta.json`
- [ ] Existing stories get metadata updated (not just on first create)

**Verification:**
- [ ] Run `python sync_pipeline.py --dry-run` → see correct author/category log output
- [ ] Check Supabase `authors` table has correct rows
- [ ] Check `stories` rows have `author_id`, `category_id`, `description` populated

**Dependencies:** Task 1 (needs extended `meta.json`)

**Files likely touched:**
- `sync_pipeline.py` (new functions: `get_or_create_author()`, `get_or_create_category()`, update `get_or_create_story()`, update `main()` flow)

**Estimated scope:** Small (1 file)

---

### Checkpoint: Phase 1

- [ ] `meta.json` contains author + category + description for test comic
- [ ] Supabase `authors` and `categories` tables populated correctly
- [ ] `stories` table has correct FK links
- [ ] Existing crawl/sync flow still works (no regressions)

---

### Phase 2: Upload Progress + Backup + Prune

---

#### Task 3: R2 upload with live CLI progress

**Description:** Add tqdm progress bar to `upload_to_r2()` in `sync_pipeline.py`. Show per-file upload with file name, size, and overall chapter progress. Use boto3's `upload_file` Callback param for byte-level tracking.

**Acceptance criteria:**
- [ ] CLI shows progress bar during R2 upload: `Uploading ch 5: 003.jpg [2.1MB] ████████░░ 80%`
- [ ] Shows total bytes uploaded per chapter after completion
- [ ] Skipped files (already exist via HEAD check) show as skipped, not uploaded

**Verification:**
- [ ] Run `python sync_pipeline.py` with a comic that has new chapters → see live progress
- [ ] Run again (all uploaded) → see "skipped" for each file, no progress bar

**Dependencies:** None (can parallel with Task 1-2)

**Files likely touched:**
- `sync_pipeline.py` (`upload_to_r2()` function)

**Estimated scope:** Small (1 file)

---

#### Task 4: Integrate rclone Drive backup into pipeline

**Description:** Add `backup_to_drive()` function in `sync_pipeline.py` that calls `rclone copy` via `subprocess.run()`. Call it after R2 upload in `main()`. Add `--skip-backup` flag to opt out. Remove the rclone line from `run_daily.bat` since it moves into Python.

**Acceptance criteria:**
- [ ] `backup_to_drive()` calls `rclone copy <DOWNLOADS_DIR> gdrive:Comic --transfers 8 --fast-list`
- [ ] Logs rclone stdout/stderr to CLI
- [ ] Returns success/failure bool
- [ ] `--skip-backup` flag skips Drive backup
- [ ] `run_daily.bat` no longer has the rclone line (avoids double backup)

**Verification:**
- [ ] Run `python sync_pipeline.py` → see Drive backup log output
- [ ] Run `python sync_pipeline.py --skip-backup` → no rclone call
- [ ] `run_daily.bat` still works end-to-end

**Dependencies:** None

**Files likely touched:**
- `sync_pipeline.py` (new `backup_to_drive()`, update `main()`)
- `run_daily.bat` (remove rclone line)
- `secrets.env.template` (add `RCLONE_REMOTE` var, optional)

**Estimated scope:** Small (3 files)

---

#### Task 5: Auto-prune local after R2 + Drive confirmed

**Description:** Add `prune_local()` function in `sync_pipeline.py`. After both R2 upload and Drive backup succeed for a chapter, delete local chapter image folder. Only prune chapters that were successfully synced this run. Add `--prune` flag (opt-in, destructive). Keep `meta.json` and comic-level folder.

**Acceptance criteria:**
- [ ] `--prune` flag enables pruning (off by default)
- [ ] Only prunes chapters that succeeded R2 upload AND Drive backup this run
- [ ] Keeps `meta.json` and comic folder structure intact
- [ ] Logs each pruned chapter: `Pruned: Comic/Chapter 005 (15 files, 42MB)`
- [ ] Dry-run mode shows what would be pruned without deleting

**Verification:**
- [ ] Run `python sync_pipeline.py --prune --dry-run` → see "[DRY-RUN] Would prune..." messages
- [ ] Run `python sync_pipeline.py --prune` with real data → local folders deleted, `meta.json` preserved

**Dependencies:** Task 4 (needs backup confirmation before prune is safe)

**Files likely touched:**
- `sync_pipeline.py` (new `prune_local()`, update `main()` flow, track prune candidates)

**Estimated scope:** Small (1 file)

---

### Checkpoint: Phase 2

- [ ] R2 upload shows live progress bar with file sizes
- [ ] Drive backup runs automatically in pipeline
- [ ] `--prune` deletes local chapters after confirmed sync
- [ ] `--dry-run` still works for all new features
- [ ] `run_daily.bat` flow unchanged from user perspective

---

### Phase 3: Discord Notification

---

#### Task 6: Rich Discord embed with comic/author/chapter details

**Description:** Rewrite `build_discord_payload()` in `sync_pipeline.py` to include author, per-comic chapter number list, and total count. Use the summary data already collected during sync. Format matches the confirmed design from intent.

**Acceptance criteria:**
- [ ] Embed shows per-comic: title, author, list of chapter numbers, count
- [ ] Shows total chapters across all comics
- [ ] Handles edge cases: no new chapters → "No new chapters today", single comic, 20+ comics (truncate)
- [ ] Embed has timestamp and color

**Verification:**
- [ ] Run `python sync_pipeline.py --dry-run` → Discord payload in stdout matches expected format
- [ ] Send real webhook → verify Discord embed renders correctly

**Dependencies:** Task 1 (needs author in summary data)

**Files likely touched:**
- `sync_pipeline.py` (`build_discord_payload()`, update summary data collection in `main()`)

**Estimated scope:** Small (1 file)

---

### Checkpoint: Complete

- [ ] All 6 tasks acceptance criteria met
- [ ] `python sync_pipeline.py --dry-run` exercises full pipeline without side effects
- [ ] `run_daily.bat` runs full flow: crawl → sync (R2 + Supabase) → backup → Discord
- [ ] Ready for daily use

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Site HTML changes break selectors | Med | Fallback to "Unknown" for all metadata; existing crawl still works |
| rclone not installed/configured | Low | `backup_to_drive()` checks for rclone binary, logs warning and continues |
| R2 upload progress callback slows uploads | Low | Callback is lightweight (counter increment); disable if measurably slower |
| Prune deletes data before backup completes | High | Prune is opt-in (`--prune`), only after both R2 + Drive confirmed |
| Supabase upsert race conditions | Low | ON CONFLICT DO NOTHING for authors/categories; idempotent |

## Open Questions

None — all resolved during interview. Ready to build.
