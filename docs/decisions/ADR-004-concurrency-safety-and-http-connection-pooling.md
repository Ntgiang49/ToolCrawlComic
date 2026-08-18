# ADR-004: Concurrency Safety and HTTP Connection Pooling

## Status
Accepted

## Date
2026-08-18

## Context
Under high concurrent workloads during multi-threaded chapter image downloads and parallel Cloudflare R2 uploads, two concurrency failure modes were identified:
1. `boto3` S3 clients are not thread-safe when shared across simultaneous worker threads in `ThreadPoolExecutor`.
2. Python's `requests.Session()` defaults to a connection pool size of 10 (`pool_maxsize=10`), causing connection thrashing and socket teardowns when crawling with $>10$ threads.
3. Repetitive relational lookups for author/category/genre metadata generated redundant REST roundtrips.

## Decision

### 1. Thread-Local Boto3 Client Isolation
- In `sync_pipeline.py`, instantiate S3 clients via `threading.local()`.
- Each worker thread in `ThreadPoolExecutor` maintains its own dedicated, thread-isolated `boto3` client instance, preventing race conditions without lock contention.

### 2. HTTPAdapter Connection Pool Sizing
- In `comic_crawler/core.py`, mount a custom `HTTPAdapter` onto `ComicCrawler.session` with `pool_connections = max(10, num_threads * 2)` and `pool_maxsize = max(10, num_threads * 2)`.
- Guarantees full HTTP keep-alive socket reuse across all worker threads.

### 3. In-Memory Memoization for Metadata Lookups
- In `sync_pipeline.py`, cache `(table, name) -> id` lookups in a run-scoped dictionary `_LOOKUP_CACHE`.
- Replaces hundreds of repetitive Supabase REST queries with $O(1)$ in-memory lookups.

### 4. Continuation Token Pagination for R2
- In `get_existing_r2_keys()`, loop with `ContinuationToken` whenever `IsTruncated=True` to support prefixes with $>1,000$ files.

## Alternatives Considered

### Global Client with Mutex Locking
- **Rejected:** Serializes uploads across worker threads and adds mutex overhead.

### Creating a New Boto3 Client on Every Image
- **Rejected:** Heavy performance penalty from repeated SSL/TLS handshakes and initialization per file.

## Consequences
- **Positive:** Robust concurrent uploads, lower network latency, zero dropped connections under high load.
- **Negative:** Slightly higher memory footprint per worker thread (negligible in Python).
