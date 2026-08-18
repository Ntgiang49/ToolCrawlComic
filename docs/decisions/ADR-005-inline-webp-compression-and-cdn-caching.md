# ADR-005: Inline WebP Optimization, Dimension Clamping, and Immutable CDN Caching

## Status
Accepted (v1.4.0)

## Context
Raw scraped comic scans from webtoon and manga sites vary wildly in file format (24-bit uncompressed PNGs, unscaled 4K JPEGs) and file size (frequently 2MB–8MB per page). Storing raw images in Cloudflare R2 quickly exhausts the 10GB free tier (~580 chapters maximum) and increases reader load times on mobile devices.

Furthermore, serving unversioned or mutable assets without explicit HTTP cache control forces Cloudflare POPs and client browsers to send redundant `If-Modified-Since` validation requests, incurring unnecessary Class B read operations.

## Decision
1. **Inline In-Memory Transcoding**:
   - Integrate `Pillow` C-accelerated libwebp transcoding (`ImageProcessor`) directly into `ComicCrawler.download_image()`.
   - Transcode all pages to WebP with lossy compression ($Q=81$, method=4) in memory before writing to disk or packing into `.cbz`.
2. **Dimension Clamping**:
   - Clamp maximum page width to $1,400\text{px}$ using high-quality Lanczos resampling while strictly preserving aspect ratio.
3. **WebP 16,383px Hard Limit Guard**:
   - The WebP specification limits coordinates to $16,383 \times 16,383\text{px}$. Extreme vertical webtoon strips exceeding this dimension automatically fallback to Progressive MozJPEG ($Q=82$) to prevent encoder crashes.
4. **Alpha Channel Stripping**:
   - Strip unused transparency masks in scanned comic pages by flattening RGBA onto a solid white RGB background.
5. **Immutable CDN Caching**:
   - Set `Cache-Control: public, max-age=31536000, immutable` and `Content-Type: image/webp` on all R2 PutObject operations.

## Consequences

### Positive
- **Storage Footprint:** Average page size drops from ~850KB to ~190KB (~75% reduction), expanding 10GB tier capacity from ~580 chapters to **~2,630+ chapters**.
- **Edge Cache Hit Ratio:** 1-year immutable caching ensures 99%+ of reader image requests are served directly from Cloudflare global edge POPs with 0ms origin revalidation.
- **Reader Performance:** Mobile devices decode 1,400px WebP images with significantly lower memory pressure and zero scrolling stutter.

### Negative / Trade-offs
- Slight increase in local crawler CPU utilization during chapter downloads (mitigated by C-libwebp bindings and multi-threaded connection pools).
