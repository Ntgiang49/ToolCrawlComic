# Task List

- [x] Task 1: Fix `crawl_full.py` crash (Add `ThreadPoolExecutor` import)
- [x] Task 2: Fix navigation links downloaded as chapters (Add blacklist to `core.py` and `config.json`)
- [x] Task 3: Make `library.json` writes atomic (Use temp file + `os.replace` in `library.py`)
- [x] Task 4: Fix decimal chapter truncation (Update regex in `sync_pipeline.py`)

**Checkpoint: Foundation**
- `run_daily.bat` executes successfully end-to-end without crashes.
- No junk chapters are downloaded.
- `library.json` remains intact under simulated interruption.

- [x] Task 5: Fix thread-unsafe boto3 client (Create client per thread in `sync_pipeline.py`)
- [x] Task 6: Handle R2 pagination (Update `list_objects_v2` in `sync_pipeline.py`)
- [x] Task 7: Implement log rotation (Update `run_daily.bat` to rotate logs)
- [x] Task 8: Check/Rotate `secrets.env` (Manual git history check - confirmed clean)

**Checkpoint: Core Features**
- Large chapters upload reliably without dropping connections.
- Existing keys are correctly identified regardless of bucket size.

- [x] Task 9: Fix `requests.Session` connection leak (Add context manager to `ComicCrawler`)
- [x] Task 10: Fix fragile `lxml` detection (Use `ImportError` in `core.py`)
- [x] Task 11: Add configurable chapter ordering (Add `chapter_order` to `config.json` and `core.py`)
- [x] Task 12: Optimize duplicate deduplication (Use set lookup in `core.py`)

- [x] Task 13: Align version strings (`__init__.py` vs `main.py`)
- [x] Task 14: Rename shadowed `format` variable (in `library.py`)
- [x] Task 15: Add `.gif` to valid exporter extensions (`exporter.py`)
- [x] Task 16: Add missing tests (Atomic writes, imports, pagination)

**Checkpoint: Complete**
- All 16 tasks implemented.
- All unit tests pass.
