# ADR-001: Cloud Sync Pipeline Architecture (R2, Supabase, Drive, Discord)

## Status
Accepted

## Date
2026-08-18

## Context
The Comic Crawler needed an automated pipeline to:
1. Store chapter images in high-performance cloud object storage for reader delivery.
2. Maintain structured comic/chapter metadata in Supabase Postgres.
3. Keep cold-storage backups on Google Drive without exhausting local disk space.
4. Provide live visual progress in CLI and automated Discord webhook alerts.

## Decision
Implement a single orchestrator pipeline in `sync_pipeline.py` executing sequentially:
1. **Local Scan**: Read `downloads/` and `meta.json` (author, categories, description, source url).
2. **Supabase Story & Metadata Upsert**: Upsert author, category, genres, and story rows before chapters.
3. **R2 Upload**: Multi-threaded upload with `tqdm` byte progress; use `list_objects_v2` for O(1) existence checks.
4. **Supabase Chapter Insert**: Batch-checked against existing chapters to avoid duplicate writes.
5. **Google Drive Backup**: `rclone copy` with `--fast-list` and 8 transfers.
6. **Atomic Auto-Prune**: Local chapter directories pruned only after R2 + Drive backup confirmation.
7. **Discord Webhook**: Rich embed notification with comic details, author, genre, and chapter lists.

## Alternatives Considered

### 1. Direct Upload during Crawler Execution
- **Pros**: Skips local staging.
- **Cons**: Crawler network failures corrupt storage state; cannot perform batch CBZ conversion or backup validation before upload.
- **Rejected**: Separating crawler from sync pipeline guarantees resilience and offline crawling capability.

### 2. S3 Head-Object Loops for Deduplication
- **Pros**: Simple 1-liner.
- **Cons**: N+1 API network calls (60 requests per chapter) causing latency bottlenecks.
- **Rejected**: Replaced with prefix `list_objects_v2` (1 call per chapter).

## Consequences
- Zero local disk accumulation via automated pruning.
- Idempotent: Can be run multiple times safely.
- Works offline / dry-run with `--dry-run`, `--skip-backup`, `--prune` flags.
