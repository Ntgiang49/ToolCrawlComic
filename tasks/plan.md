# Implementation Plan: Inline WebP Optimization & High-Performance R2 Storage Pipeline

## Overview
Implement an in-memory image compression, dimension clamping, and deduplication pipeline into the comic crawler and cloud sync orchestrator. Transcodes scanned pages (JPEG/PNG) to WebP ($Q=81$, method=4, max width=1400px) inline during crawl/sync, cutting storage footprint by ~65-75% (fitting ~4.5x more chapters within R2's 10GB free tier) and establishing 1-year immutable CDN caching.

---

## Architecture Decisions

1. **In-Memory Transcoding (Pillow C-Engine)**:
   - Use `Pillow`'s native libwebp bindings (`image.save(buffer, format="WEBP", quality=81, method=4)`) for zero-disk intermediate I/O.
2. **Dimension Clamping (Max Width 1,400px)**:
   - Rescale uncompressed 3K/4K scans down to $\le 1400$px wide using high-quality Lanczos resampling, dramatically cutting payload size with zero visible loss on mobile and desktop readers.
3. **WebP 16,383px Dimension Guard**:
   - WebP specification hard limits dimensions to 16,383px. Detect extreme vertical webtoon strips ($>16,383$px) and automatically fallback to progressive MozJPEG.
4. **Alpha Channel Stripping**:
   - Convert RGBA images with opaque alpha to RGB white-background flattening, eliminating unused alpha byte overhead.
5. **R2 Object & CDN Cache Optimization**:
   - Attach `Cache-Control: public, max-age=31536000, immutable` and `Content-Type: image/webp` to all R2 uploads.

---

## Task Breakdown

### Phase 1: Image Processing Module
- [ ] **Task 1: Build `ImageProcessor` Engine (`comic_crawler/image_processor.py`)**
  - Implement in-memory validation, corruption check, dimension resizing ($\le 1400$px), alpha flattening, and WebP transcoding.
  - Implement WebP 16,383px dimension fallback to JPEG.
  - Compute SHA-256 content checksum and return typed metadata (`ProcessedImage`).
  - *Files:* `comic_crawler/image_processor.py`
  - *Scope:* M (1 file, self-contained engine)

- [ ] **Task 2: Unit Test Suite for `ImageProcessor` (`test_image_processor.py`)**
  - Test PNG $\to$ WebP conversion, B&W scans, alpha flattening, width downsizing, corrupt image rejection, and SHA-256 hash consistency.
  - *Files:* `test_image_processor.py`
  - *Scope:* S (1 test file)

### Checkpoint 1: Image Processing Foundation
- [ ] `python -m unittest test_image_processor.py` passes with 100% green tests.

---

### Phase 2: Crawler Integration
- [ ] **Task 3: Integrate Inline Optimization into `ComicCrawler` (`comic_crawler/core.py`)**
  - Hook `ImageProcessor` into `download_image()`.
  - Store compressed `.webp` directly in chapter folders when crawling raw images or compiling CBZ archives.
  - Update `IMAGE_EXTS` across all crawler modules to include `.webp`.
  - *Files:* `comic_crawler/core.py`, `comic_crawler/exporter.py`
  - *Scope:* S (2 files)

- [ ] **Task 4: Update Exporter & CLI Format Handlers (`main.py`, `comic_crawler/exporter.py`)**
  - Ensure `.cbz` and `.pdf` exporters seamlessly pack `.webp` files.
  - *Files:* `main.py`, `comic_crawler/exporter.py`
  - *Scope:* S (2 files)

### Checkpoint 2: Crawler & Export Flow
- [ ] Crawling a live test chapter outputs optimized `.webp` files under 200KB.
- [ ] Converting to CBZ produces valid `.cbz` reader archives containing `.webp` files.

---

### Phase 3: Cloudflare R2 Upload & Supabase Pipeline Hardening
- [ ] **Task 5: Upgrade R2 Uploader with CDN Caching & WebP Headers (`sync_pipeline.py`)**
  - Set `ContentType="image/webp"` (or `"image/jpeg"` fallback).
  - Set `CacheControl="public, max-age=31536000, immutable"`.
  - Add `sha256-hash`, `image-width`, and `image-height` to S3 object metadata.
  - Update file scan filters in `scan_downloads` to prioritize `.webp`.
  - *Files:* `sync_pipeline.py`
  - *Scope:* S (1 file)

- [ ] **Task 6: Extended Sync & Pagination Tests (`test_sync_pipeline.py`)**
  - Add unit tests verifying `ContentType`, `CacheControl`, and metadata formatting in R2 uploads.
  - *Files:* `test_sync_pipeline.py`
  - *Scope:* S (1 file)

### Checkpoint 3: End-to-End Pipeline & Storage Metrics
- [ ] Full unit test suite passes.
- [ ] `sync_pipeline.py --dry-run` validates all WebP headers and Supabase payloads.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|:---|:---|:---|
| Webtoon long-strip exceeds WebP 16,383px limit | High (Encoder Crash) | Add strict dimension pre-check that automatically falls back to Progressive JPEG ($Q=82$) if height $> 16,383$px. |
| CPU overhead during high-concurrency downloads | Medium (CPU Spikes) | Scale `ThreadPoolExecutor` workers to $N_{\text{CPU}}$ and use C-accelerated Pillow libwebp bindings. |
| Corrupt partial image download from slow source | High (Broken Pages) | Verify image header integrity via `Image.open().verify()` before writing to buffer; retry on failure. |
| Older comic readers without WebP support | Low (Compatibility) | WebP in CBZ is supported by 99% of modern readers (Tachiyomi, Mihon, CDisplayEx, Kuro Reader); fallback to PDF/JPEG option remains available. |
