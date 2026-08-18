# Implementation Plan: Comic Crawler Robustness & Maintainability

## Overview
This plan outlines the systematic resolution of the 16 issues identified during the robustness review of the Comic Crawler project. The goal is to harden the pipeline against silent failures, data loss, and scale issues without rewriting working systems.

## Architecture Decisions
- **Vertical Slicing:** Fixes are grouped by impact area rather than file. Critical pipeline blockers (crashes and data loss) are addressed first, followed by silent failures (pagination, concurrency), and finally tech debt.
- **Atomic Operations:** File writes (`library.json`) must be atomic to prevent corruption on crash.
- **Fail-Fast Configuration:** Missing imports or configuration mismatches should throw immediately rather than silently doing the wrong thing.

## Task List

### Phase 1: Critical Pipeline Blockers & Data Loss
These tasks address issues that actively break the daily run or corrupt data.

- [ ] **Task 1: Fix `crawl_full.py` crash**
  - **Description:** Add the missing `ThreadPoolExecutor` import.
  - **Acceptance criteria:** `crawl_full.py` runs without throwing a `NameError`.
  - **Estimated scope:** XS (1 file)

- [ ] **Task 2: Fix navigation links downloaded as chapters**
  - **Description:** Implement a blacklist filter in `core.py` and add entries to `config.json` to reject links like "Xem thêm" or "Đọc mới nhất".
  - **Acceptance criteria:** Non-chapter navigation links are ignored and not downloaded.
  - **Estimated scope:** S (2 files)

- [ ] **Task 3: Make `library.json` writes atomic**
  - **Description:** Update `LibraryManager.save()` to write to a temp file first, then `os.replace`.
  - **Acceptance criteria:** Mid-write crashes do not result in an empty or corrupted `library.json`.
  - **Estimated scope:** XS (1 file)

- [ ] **Task 4: Fix decimal chapter truncation**
  - **Description:** Update `extract_chapter_number` in `sync_pipeline.py` to capture floats (e.g., 12.5) to prevent collisions in Supabase.
  - **Acceptance criteria:** Decimal chapters are correctly parsed and uploaded.
  - **Estimated scope:** XS (1 file)

### Checkpoint: Foundation
- [ ] `run_daily.bat` executes successfully end-to-end without crashes.
- [ ] No junk chapters are downloaded.
- [ ] `library.json` remains intact under simulated interruption.

### Phase 2: Silent Failures & Scale Issues
These tasks address issues that won't crash the pipeline but cause incorrect behavior at scale.

- [ ] **Task 5: Fix thread-unsafe boto3 client**
  - **Description:** Create a separate `boto3` client per thread in `upload_to_r2` or use `boto3.resource`.
  - **Acceptance criteria:** Concurrent uploads do not trigger connection errors.
  - **Estimated scope:** S (1 file)

- [ ] **Task 6: Handle R2 pagination**
  - **Description:** Update `get_existing_r2_keys` to handle pagination (`IsTruncated`) for prefixes with >1000 objects.
  - **Acceptance criteria:** All keys are retrieved even if the count exceeds 1000.
  - **Estimated scope:** S (1 file)

- [ ] **Task 7: Implement log rotation**
  - **Description:** Update `run_daily.bat` to rotate `crawl_daily.log` to prevent unbounded growth.
  - **Acceptance criteria:** Logs are rotated daily or limited in size.
  - **Estimated scope:** XS (1 file)

- [ ] **Task 8: Check/Rotate `secrets.env` (Manual)**
  - **Description:** Check if `secrets.env` is in git history and advise the user to rotate keys if it is.
  - **Acceptance criteria:** User is informed of potential credential leak.
  - **Estimated scope:** XS (N/A)

### Checkpoint: Core Features
- [ ] Large chapters upload reliably without dropping connections.
- [ ] Existing keys are correctly identified regardless of bucket size.

### Phase 3: Tech Debt & Future-Proofing
These tasks clean up fragile logic and prepare for new sites.

- [ ] **Task 9: Fix `requests.Session` connection leak**
  - **Description:** Implement context manager methods (`__enter__`/`__exit__`) for `ComicCrawler`.
  - **Acceptance criteria:** Sessions are cleanly closed after crawling.
  - **Estimated scope:** S (2-3 files to update usage)

- [ ] **Task 10: Fix fragile `lxml` detection**
  - **Description:** Replace `__dict__` check with standard `try/except ImportError` in `core.py`.
  - **Acceptance criteria:** `lxml` is used when installed, falling back cleanly otherwise.
  - **Estimated scope:** XS (1 file)

- [ ] **Task 11: Add configurable chapter ordering**
  - **Description:** Add `"chapter_order"` to site config to control whether to reverse the chapter list.
  - **Acceptance criteria:** Sites listing chapters oldest-first are parsed correctly without manual code changes.
  - **Estimated scope:** S (2 files: `core.py`, `config.json`)

- [ ] **Task 12: Optimize duplicate deduplication**
  - **Description:** Change O(n²) list comprehension in `parse_comic_info` to use an O(1) set lookup.
  - **Acceptance criteria:** Parsing large chapter lists is noticeably faster.
  - **Estimated scope:** XS (1 file)

### Phase 4: Polish & Coverage
- [ ] **Task 13: Align version strings**
  - **Description:** Ensure `__init__.py` and `main.py` report the same version.
  - **Acceptance criteria:** Version string is consistent.
  - **Estimated scope:** XS (2 files)

- [ ] **Task 14: Rename shadowed `format` variable**
  - **Description:** Rename `format` to `export_format` in `library.py` to avoid shadowing builtin.
  - **Acceptance criteria:** Linters report no shadowing errors.
  - **Estimated scope:** XS (1 file)

- [ ] **Task 15: Add `.gif` to valid exporter extensions**
  - **Description:** Add `.gif` to `valid_exts` in `exporter.py`.
  - **Acceptance criteria:** GIF images are successfully packed into CBZ/PDF files.
  - **Estimated scope:** XS (1 file)

- [ ] **Task 16: Add missing tests**
  - **Description:** Write tests for atomic library writes, missing imports, and pagination logic.
  - **Acceptance criteria:** Test suite covers the newly implemented fixes.
  - **Estimated scope:** M (3 files)

### Checkpoint: Complete
- [ ] All 16 tasks implemented.
- [ ] All unit tests pass (`python -m unittest discover`).

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Thread-unsafe S3 uploads fail under load | High | Explicitly scope `boto3` clients to worker threads. |
| Atomic write fails on cross-device link | Low | Ensure temp file and target file are on the same filesystem. |

## Open Questions
- Do you want me to write a script to scrub `secrets.env` from your git history if it was accidentally committed?
