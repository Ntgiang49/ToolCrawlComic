# Task List: Inline WebP Optimization & R2 Storage Pipeline

- [x] Task 1: Build `ImageProcessor` Engine (`comic_crawler/image_processor.py`)
  - In-memory validation, corruption check, dimension resizing ($\le 1400$px)
  - Alpha flattening to remove unused PNG alpha channels
  - WebP transcoding ($Q=81$, method=4) with 16,383px JPEG fallback
  - SHA-256 hash generation for deduplication

- [x] Task 2: Unit Test Suite for `ImageProcessor` (`test_image_processor.py`)
  - Test PNG/JPEG $\to$ WebP transcode, resizing, alpha flattening, 16383px guard, and corrupt image rejection

**Checkpoint 1: Image Processing Foundation**
- [x] `python -m unittest test_image_processor.py` passes 100%.

- [x] Task 3: Integrate Inline WebP Optimization into `ComicCrawler` (`comic_crawler/core.py`)
  - Transcode raw image bytes inline before saving to disk/exporting
  - Add `.webp` to `IMAGE_EXTS`

- [x] Task 4: Update Exporters and CLI Handlers (`comic_crawler/exporter.py`, `main.py`)
  - Ensure `.cbz` and `.pdf` packing supports `.webp` files seamlessly

**Checkpoint 2: Crawler & Export Integration**
- [x] Live chapter crawl saves compact `.webp` pages.
- [x] `main.py convert` packs `.webp` into CBZ.

- [x] Task 5: Upgrade R2 Uploader with CDN Caching & WebP Headers (`sync_pipeline.py`)
  - Set `ContentType="image/webp"`
  - Set `CacheControl="public, max-age=31536000, immutable"`
  - Pass `sha256-hash`, `image-width`, `image-height` in S3 metadata

- [x] Task 6: Add Sync Pipeline WebP and Header Unit Tests (`test_sync_pipeline.py`)
  - Verify headers and metadata in S3 upload mocks

**Checkpoint 3: Complete**
- [x] All 36 unit tests pass.
- [x] End-to-end dry-run and live crawl verification complete.
