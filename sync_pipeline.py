#!/usr/bin/env python3
"""Sync pipeline: scan downloads → upload R2 (batch listed) → upsert Supabase (batch queried) → Drive backup → auto-prune → Discord notify."""

import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import threading
from concurrent.futures import ThreadPoolExecutor

if sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', write_through=True)

import boto3
import requests
from tqdm import tqdm

# --- Config from env & secrets.env fallback ---
def _load_env_file(path: str = "secrets.env") -> None:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("\"'")
                        if k and not os.environ.get(k):
                            os.environ[k] = v
        except Exception:
            pass

_load_env_file("secrets.env")
_load_env_file(".env")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
R2_BUCKET = os.environ.get("R2_BUCKET_NAME", "comic")
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_PUBLIC_URL = os.environ.get(
    "R2_PUBLIC_URL",
    "https://pub-006586cb2a0d4198bcd302b9b8f8ea45.r2.dev",
).rstrip("/")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
DOWNLOADS_DIR = os.environ.get("DOWNLOADS_DIR", "downloads")
RCLONE_REMOTE = os.environ.get("RCLONE_REMOTE", "gdrive:Comic")
CHAPTER_BATCH_SIZE = int(os.environ.get("CHAPTER_BATCH_SIZE", "10"))
R2_MAX_WORKERS = int(os.environ.get("R2_MAX_WORKERS", "4"))
SUPABASE_MAX_WORKERS = int(os.environ.get("SUPABASE_MAX_WORKERS", "2"))

# CLI flags
DRY_RUN = "--dry-run" in sys.argv
SKIP_BACKUP = "--skip-backup" in sys.argv
PRUNE_ENABLED = "--prune" in sys.argv

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
CBZ_EXTS = {".cbz"}
MIME_MAP = {
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".cbz": "application/vnd.comicbook+zip",
}


def sb_enabled() -> bool:
    """Supabase DB operations enabled when URL + service key are configured."""
    return bool(SUPABASE_URL and SUPABASE_KEY)


# ── Helpers ──────────────────────────────────────────────────────────


def slugify(text: str) -> str:
    """Convert title to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def r2_asset_url(r2_prefix: str, local_file: Path) -> str:
    """Build a cache-busted public URL for a local asset."""
    version = f"{local_file.stat().st_size}-{local_file.stat().st_mtime_ns}"
    return f"{R2_PUBLIC_URL}/{r2_prefix}/{local_file.name}?v={version}"


def extract_chapter_number(folder_name: str) -> float | int | None:
    """Extract chapter number (int or float) from folder name ('Chapter 001' → 1, 'Chapter 012.5' → 12.5, 'Chapter 0' → 0)."""
    # Match explicit chapter keywords first to avoid capturing volume or season numbers (e.g. 'Vol. 1 Chapter 12')
    match = re.search(r"(?:chapter|ch\.?|tập|chuong)\s*(\d+(?:\.\d+)?)", folder_name, re.IGNORECASE)
    if not match:
        match = re.search(r"(\d+(?:\.\d+)?)", folder_name)
    if match:
        val = float(match.group(1))
        if val >= 0:
            return int(val) if val.is_integer() else val
    return None


def _natural_sort_key(p: Path):
    """Sort filenames naturally (001, 2, 10 instead of 1, 10, 2)."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", p.name)]


def chunk_chapters(chapters: list, batch_size: int | None = None) -> list[list]:
    """Split a chapter list into configurable batches, defaulting to 10."""
    size = int(batch_size or CHAPTER_BATCH_SIZE)
    if size <= 0:
        size = 10
    return [chapters[i:i + size] for i in range(0, len(chapters), size)]


def _retryable_http_status(exc: Exception) -> bool:
    """Return True for HTTP 429 / 5xx style errors that should be retried with backoff."""
    status = None
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
    elif isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = exc.response.status_code

    if status is not None:
        return status == 429 or 500 <= int(status) <= 599

    if isinstance(exc, Exception):
        error_name = str(exc).upper()
        if any(token in error_name for token in ("429", "TOOMANYREQUESTS", "RATE_LIMIT", "RATE-LIMIT", "THROTTL")):
            return True
        if any(token in error_name for token in ("500", "502", "503", "504", "SERVICE UNAVAILABLE", "INTERNALERROR", "TIMEOUT")):
            return True

    return False


def with_retry(operation, label: str, max_retries: int = 3, base_delay: float = 1.0):
    """Invoke an operation with exponential backoff and jitter for HTTP 429/5xx responses."""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return operation()
        except Exception as exc:
            last_exc = exc
            if not _retryable_http_status(exc) or attempt >= max_retries:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0.0, 0.5)
            print(f"  [Retry] {label} failed ({type(exc).__name__}: {exc}). Retrying in {delay:.2f}s ({attempt + 1}/{max_retries})", file=sys.stderr)
            time.sleep(delay)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"Retry loop for {label} exited without an exception")


def chapter_key(number: float | int) -> str:
    """Return a stable JSON key for a chapter number."""
    return str(number)


def save_meta(meta_path: Path, meta: dict) -> None:
    """Persist metadata atomically so sync state survives interruptions."""
    temp_path = meta_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(meta_path)


def scan_downloads(downloads: Path) -> list[dict]:
    """Load comic manifests and materialize only chapters still pending sync."""
    comics = []
    for comic_dir in sorted(downloads.iterdir()):
        if not comic_dir.is_dir() or comic_dir.name.startswith("_"):
            continue

        title = comic_dir.name
        slug = slugify(title)
        meta = {}
        meta_file = comic_dir / "meta.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        chapters_by_number = {}
        manifest = meta.get("chapters", {})
        if isinstance(manifest, dict) and manifest:
            for key, entry in manifest.items():
                if not isinstance(entry, dict) or entry.get("synced") is True:
                    continue
                try:
                    ch_num = float(entry.get("number", key))
                    ch_num = int(ch_num) if ch_num.is_integer() else ch_num
                except (TypeError, ValueError):
                    continue
                local_name = entry.get("local_name") or entry.get("title") or f"Chapter {ch_num}"
                local_path = comic_dir / local_name
                export_format = entry.get("format", "images")
                if export_format == "cbz":
                    if local_path.suffix.lower() != ".cbz":
                        local_path = comic_dir / f"{local_name}.cbz"
                    if not local_path.is_file():
                        continue
                    chapters_by_number[ch_num] = {
                        "file": local_path,
                        "number": ch_num,
                        "title": entry.get("title", local_path.stem),
                        "images": [],
                        "format": "cbz",
                        "sync_pending": True,
                    }
                else:
                    if not local_path.is_dir():
                        continue
                    images = sorted(
                        (f for f in local_path.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS),
                        key=_natural_sort_key,
                    )
                    if images:
                        chapters_by_number[ch_num] = {
                            "dir": local_path,
                            "number": ch_num,
                            "title": entry.get("title", local_path.name),
                            "images": images,
                            "format": "images",
                            "sync_pending": True,
                        }
        else:
            # Legacy metadata is scanned once to bootstrap the manifest format.
            for ch_dir in sorted(comic_dir.iterdir()):
                if not ch_dir.is_dir() or ch_dir.name.startswith("_"):
                    continue
                ch_num = extract_chapter_number(ch_dir.name)
                if ch_num is None:
                    continue
                images = sorted(
                    (f for f in ch_dir.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS),
                    key=_natural_sort_key,
                )
                if images:
                    chapters_by_number[ch_num] = {
                        "dir": ch_dir, "number": ch_num, "title": ch_dir.name,
                        "images": images, "format": "images", "sync_pending": True,
                    }
            for cbz_file in sorted(comic_dir.iterdir(), key=_natural_sort_key):
                if not cbz_file.is_file() or cbz_file.suffix.lower() not in CBZ_EXTS:
                    continue
                ch_num = extract_chapter_number(cbz_file.stem)
                if ch_num is not None and ch_num not in chapters_by_number:
                    chapters_by_number[ch_num] = {
                        "file": cbz_file, "number": ch_num, "title": cbz_file.stem,
                        "images": [], "format": "cbz", "sync_pending": True,
                    }

        chapters = sorted(chapters_by_number.values(), key=lambda chapter: chapter["number"])

        if chapters or (isinstance(manifest, dict) and manifest):
            comics.append(
                {
                    "title": title,
                    "slug": slug,
                    "author": meta.get("author", "Unknown"),
                    "category": meta.get("category", "Unknown"),
                    "description": meta.get("description", ""),
                    "url": meta.get("url", ""),
                    "meta_path": meta_file,
                    "meta": meta,
                    "dir": comic_dir,
                    "chapters": chapters,
                }
            )

    return comics


# ── Supabase REST ────────────────────────────────────────────────────


def _sb_headers(*, want_return: bool = False) -> dict:
    h = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if want_return:
        h["Prefer"] = "return=representation"
    return h


def supabase_get(table: str, params: dict) -> list:
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/{table}", headers=_sb_headers(), params=params, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def supabase_post(table: str, data: dict) -> list:
    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=_sb_headers(want_return=True),
        json=data,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def supabase_patch(table: str, params: dict, data: dict) -> list:
    resp = requests.patch(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=_sb_headers(want_return=True),
        params=params,
        json=data,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


_LOOKUP_CACHE: dict[tuple[str, str], str] = {}


def _get_or_create_named_row(table: str, name: str, dry_run_id: str) -> str | None:
    """Helper to get or insert a row by name in a lookup table (authors, categories, genres) with in-memory caching."""
    clean_name = name.strip()
    if not clean_name or clean_name == "Unknown":
        return None
    if DRY_RUN:
        return dry_run_id
    if not sb_enabled():
        return None

    cache_key = (table, clean_name)
    if cache_key in _LOOKUP_CACHE:
        return _LOOKUP_CACHE[cache_key]

    try:
        existing = supabase_get(table, {"name": f"eq.{clean_name}", "select": "id"})
        if existing:
            row_id = existing[0]["id"]
            _LOOKUP_CACHE[cache_key] = row_id
            return row_id
        res = supabase_post(table, {"name": clean_name})
        if res:
            row_id = res[0]["id"]
            _LOOKUP_CACHE[cache_key] = row_id
            return row_id
        return None
    except Exception as e:
        print(f"  [Warning] {table} lookup/create failed for '{clean_name}': {e}", file=sys.stderr)
        return None


def get_or_create_author(name: str) -> str | None:
    return _get_or_create_named_row("authors", name, "dry-run-author-id")


def get_or_create_category(category_name: str) -> str | None:
    primary = [c.strip() for c in category_name.split(",") if c.strip()]
    first_cat = primary[0] if primary else category_name
    return _get_or_create_named_row("categories", first_cat, "dry-run-category-id")


def get_or_create_genre(genre_name: str) -> str | None:
    return _get_or_create_named_row("genres", genre_name, "dry-run-genre-id")


def sync_story_genres(story_id: str, category_string: str) -> None:
    """Link all comma-separated genres to story_genres junction table."""
    if not category_string or category_string == "Unknown" or DRY_RUN or not story_id or not sb_enabled():
        return
    genres = [g.strip() for g in category_string.split(",") if g.strip() and g.strip() != "Unknown"]
    for g_name in genres:
        genre_id = get_or_create_genre(g_name)
        if genre_id and genre_id != "dry-run-genre-id":
            try:
                supabase_post("story_genres", {"story_id": story_id, "genre_id": genre_id})
            except requests.HTTPError as e:
                if e.response is None or e.response.status_code != 409:
                    print(f"  [Warning] Failed to link genre '{g_name}': {e}", file=sys.stderr)


def get_or_create_crawler_source(url: str) -> str | None:
    """Register source domain in crawler_sources."""
    if not url:
        return None
    domain = urlparse(url).netloc.lower() or "unknown-source"
    if DRY_RUN:
        return "dry-run-source-id"
    if not sb_enabled():
        return None
    try:
        existing = supabase_get("crawler_sources", {"name": f"eq.{domain}", "select": "id"})
        if existing:
            source_id = existing[0]["id"]
            supabase_patch(
                "crawler_sources",
                {"id": f"eq.{source_id}"},
                {"last_crawled_at": datetime.now(timezone.utc).isoformat(), "last_status": "active"},
            )
            return source_id
        res = supabase_post(
            "crawler_sources",
            {
                "name": domain,
                "source_type": "html",
                "source_url": f"https://{domain}",
                "enabled": True,
                "last_crawled_at": datetime.now(timezone.utc).isoformat(),
                "last_status": "active",
            },
        )
        return res[0]["id"] if res else None
    except Exception as e:
        print(f"  [Warning] Crawler source lookup/create failed: {e}", file=sys.stderr)
        return None


def record_crawler_run(
    source_id: str | None,
    started_at: datetime,
    items_seen: int,
    items_created: int,
    items_updated: int,
    log_text: str = "",
    status: str = "succeeded",
) -> None:
    """Record execution metrics in crawler_runs table."""
    if not sb_enabled() or DRY_RUN:
        return
    try:
        # Map common aliases to match PostgreSQL check constraint ('queued', 'running', 'succeeded', 'failed')
        db_status = "succeeded" if status in ("completed", "succeeded") else status
        payload = {
            "status": db_status,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "items_seen": items_seen,
            "items_created": items_created,
            "items_updated": items_updated,
            "log": log_text[:5000] if log_text else "Sync completed successfully",
        }
        if source_id:
            payload["source_id"] = source_id
        supabase_post("crawler_runs", payload)
    except Exception as e:
        print(f"  [Warning] Failed to record crawler run: {e}", file=sys.stderr)


def get_or_create_story(
    title: str,
    slug: str,
    cover_url: str | None,
    author: str = "AutoCrawler",
    category: str = "Unknown",
    description: str = "",
) -> str | None:
    """Get existing story by slug (updating missing metadata), or create new."""
    if DRY_RUN:
        print(f"  [DRY-RUN] Would create story: {title} ({slug}) [Author: {author}, Cat: {category}]")
        return "dry-run-id"
    if not sb_enabled():
        return None

    author_id = get_or_create_author(author)
    category_id = get_or_create_category(category)

    existing = supabase_get(
        "stories",
        {"slug": f"eq.{slug}", "select": "id,author,category,description,author_id,category_id"},
    )
    if existing:
        story_id = existing[0]["id"]
        update_data = {}
        if author and author != "Unknown" and existing[0].get("author") in ("Unknown", "AutoCrawler", None, ""):
            update_data["author"] = author
        if author_id and not existing[0].get("author_id"):
            update_data["author_id"] = author_id
        if category and category != "Unknown" and not existing[0].get("category"):
            update_data["category"] = category
        if category_id and not existing[0].get("category_id"):
            update_data["category_id"] = category_id
        if description and not existing[0].get("description"):
            update_data["description"] = description
        if update_data:
            try:
                supabase_patch("stories", {"id": f"eq.{story_id}"}, update_data)
            except Exception as e:
                print(f"  [Warning] Failed to update story metadata: {e}", file=sys.stderr)
        sync_story_genres(story_id, category)
        return story_id

    story_payload = {
        "title": title,
        "slug": slug,
        "status": "published",
        "author": author if author != "Unknown" else "AutoCrawler",
        "cover_url": cover_url,
    }
    if author_id:
        story_payload["author_id"] = author_id
    if category and category != "Unknown":
        story_payload["category"] = category
    if category_id:
        story_payload["category_id"] = category_id
    if description:
        story_payload["description"] = description

    try:
        result = supabase_post("stories", story_payload)
        story_id = result[0]["id"] if result else None
        if story_id:
            sync_story_genres(story_id, category)
        return story_id
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 409:
            import hashlib
            hash_suffix = hashlib.md5(title.encode()).hexdigest()[:6]
            story_payload["slug"] = f"{slug}-{hash_suffix}"
            result = supabase_post("stories", story_payload)
            story_id = result[0]["id"] if result else None
            if story_id:
                sync_story_genres(story_id, category)
            return story_id
        raise


def get_existing_chapter_numbers(story_id: str) -> set[float | int]:
    """Batch fetch all existing chapter numbers for a story with PostgREST pagination."""
    if not sb_enabled() or DRY_RUN or not story_id:
        return set()
    existing = set()
    limit = 1000
    offset = 0
    try:
        while True:
            res = supabase_get(
                "chapters",
                {
                    "story_id": f"eq.{story_id}",
                    "select": "chapter_number",
                    "limit": str(limit),
                    "offset": str(offset),
                },
            )
            if not res:
                break
            for r in res:
                if "chapter_number" in r and r["chapter_number"] is not None:
                    val = float(r["chapter_number"])
                    existing.add(int(val) if val.is_integer() else val)
            if len(res) < limit:
                break
            offset += limit
        return existing
    except Exception as e:
        print(f"  [Warning] Failed to batch fetch existing chapters: {e}", file=sys.stderr)
        return existing


# ── R2 Upload ────────────────────────────────────────────────────────

_thread_local = threading.local()


def _get_r2_client():
    """Returns a thread-local boto3 S3 client to avoid concurrency issues."""
    if not hasattr(_thread_local, "client"):
        endpoint = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else None
        _thread_local.client = boto3.session.Session().client(
            "s3",
            endpoint_url=endpoint,
            region_name="auto",
            aws_access_key_id=R2_ACCESS_KEY_ID or None,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY or None,
        )
    return _thread_local.client


def get_existing_r2_keys(client, prefix: str) -> set[str]:
    """Fetch all existing object keys under prefix handling pagination with strict trailing slash prefixing."""
    keys = set()
    continuation_token = None
    # Ensure strict prefix boundary to avoid prefix overlap bleed (e.g. ch_1 matching ch_10, ch_100)
    query_prefix = prefix if prefix.endswith("/") else f"{prefix}/"
    try:
        while True:
            kwargs = {"Bucket": R2_BUCKET, "Prefix": query_prefix}
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            resp = client.list_objects_v2(**kwargs)
            if "Contents" in resp:
                for obj in resp["Contents"]:
                    keys.add(obj["Key"])
            if resp.get("IsTruncated") and resp.get("NextContinuationToken"):
                continuation_token = resp["NextContinuationToken"]
            else:
                break
    except Exception as e:
        print(f"  [Warning] Failed to list R2 objects for prefix '{query_prefix}': {e}", file=sys.stderr)
    return keys


def get_existing_r2_sizes(client, prefix: str) -> dict[str, int]:
    """Fetch object sizes under a prefix so stale objects can be replaced."""
    sizes = {}
    continuation_token = None
    query_prefix = prefix if prefix.endswith("/") else f"{prefix}/"
    try:
        while True:
            kwargs = {"Bucket": R2_BUCKET, "Prefix": query_prefix}
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            resp = client.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []):
                sizes[obj["Key"]] = obj.get("Size", -1)
            if resp.get("IsTruncated") and resp.get("NextContinuationToken"):
                continuation_token = resp["NextContinuationToken"]
            else:
                break
    except Exception as e:
        print(f"  [Warning] Failed to inspect R2 objects for prefix '{query_prefix}': {e}", file=sys.stderr)
    return sizes


def chapter_already_on_r2(chapter: dict, slug: str) -> bool:
    """Check whether the required chapter objects already exist in R2 using manifest and key prefix data."""
    if not chapter:
        return False

    client = _get_r2_client()
    r2_prefix = f"chapters/{slug}/ch_{chapter['number']}"
    if chapter.get("format") == "cbz":
        if "file" not in chapter:
            return False
        return f"{r2_prefix}/{chapter['file'].name}" in get_existing_r2_keys(client, r2_prefix)

    if "dir" not in chapter:
        return False
    expected = {
        f"{r2_prefix}/{p.name}"
        for p in chapter["dir"].iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    }
    if not expected:
        return False
    existing = get_existing_r2_keys(client, r2_prefix)
    return expected.issubset(existing)


def upload_to_r2(local_dir: Path, r2_prefix: str, *, compare_existing: bool = True) -> bool:
    """Upload chapter images to R2 with thread-safe tqdm byte progress bar."""
    if DRY_RUN:
        print(f"  [DRY-RUN] Would upload {local_dir} to s3://{R2_BUCKET}/{r2_prefix}")
        return True

    main_client = _get_r2_client()
    try:
        imgs = sorted([p for p in local_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS])
        if not imgs:
            print(f"  [Warning] No images found in {local_dir} to upload.", file=sys.stderr)
            return False

        if compare_existing:
            existing_sizes = get_existing_r2_sizes(main_client, r2_prefix)
            to_upload = [
                img for img in imgs
                if existing_sizes.get(f"{r2_prefix}/{img.name}", -1) != img.stat().st_size
            ]
        else:
            to_upload = imgs

        if not to_upload:
            print(f"  All {len(imgs)} images already in R2 (skipped)")
            return True

        stale_count = 0
        if compare_existing:
            stale_count = sum(
                1 for img in to_upload
                if f"{r2_prefix}/{img.name}" in existing_sizes
            )
        if stale_count:
            print(f"  Replacing {stale_count} stale R2 image(s)")

        total_bytes = sum(p.stat().st_size for p in to_upload)
        pbar_lock = threading.Lock()

        with tqdm(
            total=total_bytes,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=f"  R2 -> {local_dir.name[:24]}",
            leave=False,
        ) as pbar:
            def _upload(img: Path) -> None:
                key = f"{r2_prefix}/{img.name}"
                thread_client = _get_r2_client()

                def _safe_update(bytes_transferred: int) -> None:
                    with pbar_lock:
                        pbar.update(bytes_transferred)

                extra_args = {
                    "ContentType": MIME_MAP.get(img.suffix.lower(), "application/octet-stream"),
                    "CacheControl": "public, max-age=31536000, immutable",
                    "ContentDisposition": "inline",
                }

                def _upload_once() -> None:
                    thread_client.upload_file(
                        str(img),
                        R2_BUCKET,
                        key,
                        ExtraArgs=extra_args,
                        Callback=_safe_update,
                    )

                with_retry(_upload_once, f"upload {key} to R2", max_retries=3, base_delay=1.0)

            with ThreadPoolExecutor(max_workers=R2_MAX_WORKERS) as ex:
                list(ex.map(_upload, to_upload))

        print(f"  ✓ Uploaded {len(to_upload)}/{len(imgs)} image(s) ({total_bytes / (1024 * 1024):.1f} MB)")
    except Exception as e:
        print(f"  ERROR uploading: {e}", file=sys.stderr)
        return False
    return True


def upload_cbz_to_r2(cbz_file: Path, r2_prefix: str, *, compare_existing: bool = True) -> bool:
    """Upload a CBZ archive to R2 with immutable caching headers."""
    key = f"{r2_prefix}/{cbz_file.name}"
    if DRY_RUN:
        print(f"  [DRY-RUN] Would upload {cbz_file} to s3://{R2_BUCKET}/{key}")
        return True

    try:
        client = _get_r2_client()
        if compare_existing:
            existing_sizes = get_existing_r2_sizes(client, r2_prefix)
        else:
            existing_sizes = {}
        if compare_existing and existing_sizes.get(key) == cbz_file.stat().st_size:
            print(f"  CBZ already in R2 (skipped): {cbz_file.name}")
            return True

        def _upload_once() -> None:
            client.upload_file(
                str(cbz_file),
                R2_BUCKET,
                key,
                ExtraArgs={
                    "ContentType": MIME_MAP[".cbz"],
                    "CacheControl": "public, max-age=31536000, immutable",
                    "ContentDisposition": "inline",
                },
            )

        with_retry(_upload_once, f"upload {key} to R2", max_retries=3, base_delay=1.0)
        print(f"  ✓ Uploaded CBZ: {cbz_file.name}")
        return True
    except Exception as e:
        print(f"  ERROR uploading CBZ: {e}", file=sys.stderr)
        return False


# ── Backup & Prune ───────────────────────────────────────────────────


def backup_to_drive(downloads_dir: Path) -> bool:
    """Run rclone copy to backup downloads to Google Drive with strict safety checks."""
    if SKIP_BACKUP:
        print("\n[Drive] Backup skipped (--skip-backup)")
        return True

    if not shutil.which("rclone"):
        print("\n[Drive] Error: 'rclone' executable not found in PATH. Aborting Drive backup to prevent unsafe local pruning.", file=sys.stderr)
        return False

    if DRY_RUN:
        print(f"\n[DRY-RUN] Would run: rclone copy \"{downloads_dir}\" {RCLONE_REMOTE} --transfers 8 --fast-list")
        return True

    print(f"\n[Drive] Backing up \"{downloads_dir}\" -> {RCLONE_REMOTE}...")
    try:
        proc = subprocess.run(
            ["rclone", "copy", str(downloads_dir), RCLONE_REMOTE, "--transfers", "8", "--fast-list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
        )
        if proc.returncode != 0:
            print(f"  [ERROR] rclone backup failed (code {proc.returncode}): {proc.stderr}", file=sys.stderr)
            return False
        print("  ✓ Google Drive backup completed successfully")
        return True
    except Exception as e:
        print(f"  [ERROR] rclone backup execution failed: {e}", file=sys.stderr)
        return False


def prune_local_chapters(synced_chapters: list[dict]) -> None:
    """Prune local chapter directories or CBZ files after confirmed sync."""
    if not PRUNE_ENABLED:
        return

    print(f"\n[Prune] Pruning {len(synced_chapters)} synced chapter folder(s)...")
    pruned_count = 0
    freed_bytes = 0

    for item in synced_chapters:
        local_path = item.get("dir")
        if not local_path or not local_path.exists():
            continue

        if local_path.is_file():
            dir_size = local_path.stat().st_size
            file_count = 1
        elif local_path.is_dir():
            dir_size = sum(f.stat().st_size for f in local_path.iterdir() if f.is_file())
            file_count = len([f for f in local_path.iterdir() if f.is_file()])
        else:
            continue

        if DRY_RUN:
            print(f"  [DRY-RUN] Would prune: {local_path.parent.name}/{local_path.name} ({file_count} files, {dir_size / (1024 * 1024):.1f} MB)")
        else:
            try:
                if local_path.is_file():
                    local_path.unlink()
                else:
                    shutil.rmtree(local_path)
                print(f"  ✓ Pruned: {local_path.parent.name}/{local_path.name} ({file_count} files, {dir_size / (1024 * 1024):.1f} MB)")
            except Exception as e:
                print(f"  [Warning] Failed to prune {local_path}: {e}", file=sys.stderr)
                continue

        pruned_count += 1
        freed_bytes += dir_size

    print(f"  Pruning summary: {pruned_count} folder(s) removed, {freed_bytes / (1024 * 1024):.1f} MB freed.")


# ── Discord ──────────────────────────────────────────────────────────


def build_discord_payload(summary: list[dict], duration_seconds: float = 0.0) -> dict:
    """Rich Discord embed payload from sync summary with timing observability."""
    comics_map: dict[str, dict] = {}
    for item in summary:
        c_name = item["comic"]
        if c_name not in comics_map:
            comics_map[c_name] = {
                "author": item.get("author", "Unknown"),
                "category": item.get("category", "Unknown"),
                "chapters": [],
            }
        comics_map[c_name]["chapters"].append(str(item["chapter"]))

    fields = []
    for name, data in list(comics_map.items())[:20]:
        author_str = f" *(by {data['author']})*" if data["author"] and data["author"] != "Unknown" else ""
        cat_str = f" • *[{data['category']}]*" if data.get("category") and data["category"] != "Unknown" else ""
        ch_list = data["chapters"]
        ch_str = ", ".join(ch_list) if len(ch_list) <= 10 else f"{', '.join(ch_list[:8])}, ... (+{len(ch_list) - 8} more)"

        fields.append(
            {
                "name": f"🔹 {name}{author_str}{cat_str}".strip(),
                "value": f"**Chapters ({len(ch_list)}):** {ch_str}",
                "inline": False,
            }
        )

    footer_text = (
        f"Comic Crawler Easy • R2 + Supabase • Duration: {duration_seconds:.1f}s"
        if duration_seconds > 0
        else "Comic Crawler Easy • R2 + Supabase"
    )

    return {
        "embeds": [
            {
                "title": "📚 Comic Crawler & Sync Report",
                "description": f"🚀 **Uploaded {len(summary)} new chapter(s)** across **{len(comics_map)} comic(s)**" if summary else "😴 No new chapters synced today",
                "color": 3066993 if summary else 9807270,
                "fields": fields,
                "footer": {"text": footer_text},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }


def send_discord(summary: list[dict], duration_seconds: float = 0.0) -> None:
    """Send Discord webhook notification with execution duration."""
    if not DISCORD_WEBHOOK:
        print("DISCORD_WEBHOOK_URL not set, skipping notification")
        return

    payload = build_discord_payload(summary, duration_seconds)
    if DRY_RUN:
        print(f"\n[DRY-RUN] Discord payload:\n{json.dumps(payload, indent=2, ensure_ascii=False)}")
        return

    resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=30)
    if resp.status_code not in (200, 204):
        print(f"Discord webhook failed: {resp.status_code} {resp.text}", file=sys.stderr)


# ── Diagnostics ──────────────────────────────────────────────────────


def run_health_check() -> bool:
    """Diagnostic check verifying R2, Supabase, Google Drive, and Discord connectivity."""
    print("=" * 55)
    print(" ToolCrawlComic - Pipeline Health & Diagnostic Check")
    print("=" * 55)
    all_ok = True

    # 1. Cloudflare R2
    try:
        client = _get_r2_client()
        client.head_bucket(Bucket=R2_BUCKET)
        print(f" [OK] Cloudflare R2: Connected (Bucket: '{R2_BUCKET}')")
    except Exception as e:
        print(f" [FAIL] Cloudflare R2: Connection error: {e}")
        all_ok = False

    # 2. Supabase PostgreSQL
    if sb_enabled():
        try:
            res = supabase_get("crawler_sources", {"select": "id", "limit": "1"})
            print(f" [OK] Supabase DB: Connected ({SUPABASE_URL})")
        except Exception as e:
            print(f" [FAIL] Supabase DB: Query error: {e}")
            all_ok = False
    else:
        print(" [WARN] Supabase DB: Credentials missing in env (SUPABASE_URL / SUPABASE_SERVICE_KEY)")

    # 3. Google Drive / rclone
    if shutil.which("rclone"):
        print(f" [OK] Google Drive (rclone): Executable found (Remote: '{RCLONE_REMOTE}')")
    else:
        print(" [WARN] Google Drive (rclone): 'rclone' executable not found in PATH")

    # 4. Discord Webhook
    if DISCORD_WEBHOOK and DISCORD_WEBHOOK.startswith("https://discord.com/api/webhooks/"):
        print(" [OK] Discord Webhook: Configured")
    else:
        print(" [WARN] Discord Webhook: DISCORD_WEBHOOK_URL not configured")

    # 5. Local Downloads Directory
    downloads_path = Path(DOWNLOADS_DIR)
    try:
        downloads_path.mkdir(parents=True, exist_ok=True)
        test_file = downloads_path / ".health_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        print(f" [OK] Downloads Directory: Ready & writable ('{downloads_path.resolve()}')")
    except Exception as e:
        print(f" [FAIL] Downloads Directory: Not writable: {e}")
        all_ok = False

    print("=" * 55)
    if all_ok:
        print(" Status: ALL CRITICAL SYSTEMS OPERATIONAL (Healthy)")
    else:
        print(" Status: ISSUES DETECTED - Please verify credentials above")
    print("=" * 55)
    return all_ok


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    if "--health" in sys.argv or "--check" in sys.argv:
        healthy = run_health_check()
        sys.exit(0 if healthy else 1)

    started_at = datetime.now(timezone.utc)
    downloads = Path(DOWNLOADS_DIR)
    if not downloads.exists():
        print(f"Downloads directory not found: {downloads}")
        sys.exit(0)

    if DRY_RUN:
        print("=== DRY RUN MODE ===\n")

    print(f"Scanning downloads: {downloads.resolve()}...", flush=True)
    comics = scan_downloads(downloads)
    print(
        f"Scan complete: {len(comics)} comic(s), "
        f"{sum(len(comic['chapters']) for comic in comics)} chapter(s) found.",
        flush=True,
    )
    if not comics:
        print("No comics found in downloads/")
        sys.exit(0)

    target_comic = None
    if "--comic" in sys.argv:
        idx = sys.argv.index("--comic")
        if idx + 1 < len(sys.argv):
            target_comic = sys.argv[idx + 1].strip().lower()

    if target_comic:
        comics = [
            c for c in comics
            if target_comic in c["title"].lower() or target_comic in c["slug"].lower()
        ]
        if not comics:
            print(f"No matching comic found for '{target_comic}' in downloads/")
            sys.exit(0)

    summary: list[dict] = []
    synced_for_prune: list[dict] = []
    items_seen = 0
    items_created = 0
    items_updated = 0
    primary_source_id = None

    def _supabase_upsert_chapter(ch: dict, story_id: str | None, slug: str) -> None:
        if not ch.get("sync_pending", True):
            return
        ch_num = ch["number"]
        r2_prefix = f"chapters/{slug}/ch_{ch_num}"

        if ch["format"] == "cbz":
            content = json.dumps([r2_asset_url(r2_prefix, ch["file"])])
        else:
            content = json.dumps([r2_asset_url(r2_prefix, img) for img in ch["images"]])

        chapter_payload = {
            "story_id": story_id,
            "chapter_number": ch_num,
            "title": ch["title"],
            "content": content,
            "status": "published",
            "published_at": datetime.now(timezone.utc).isoformat(),
        }

        def _do_upsert() -> None:
            if sb_enabled() and not DRY_RUN:
                try:
                    supabase_post("chapters", chapter_payload)
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 409:
                        supabase_patch(
                            "chapters",
                            {
                                "story_id": f"eq.{story_id}",
                                "chapter_number": f"eq.{ch_num}",
                            },
                            chapter_payload,
                        )
                    else:
                        raise
                except Exception:
                    raise
            elif DRY_RUN:
                return

        with_retry(_do_upsert, f"Supabase chapter {ch_num} insert", max_retries=3, base_delay=1.0)

    try:
        for comic in comics:
            title = comic["title"]
            slug = comic["slug"]
            author = comic["author"]
            category = comic["category"]
            description = comic["description"]
            url = comic["url"]
            meta = comic["meta"]
            meta_path = comic["meta_path"]

            if url and not primary_source_id and sb_enabled():
                primary_source_id = get_or_create_crawler_source(url)

            print(f"\n{'─' * 40}")
            print(f"Comic: {title} (slug: {slug})")
            if author and author != "Unknown":
                print(f"  Author: {author}")
            if category and category != "Unknown":
                print(f"  Category: {category}")

            cover_url = None
            if comic["chapters"] and comic["chapters"][0]["format"] == "images":
                first_ch = comic["chapters"][0]
                cover_url = r2_asset_url(
                    f"chapters/{slug}/ch_{first_ch['number']}",
                    first_ch["images"][0],
                )

            story_id = (
                get_or_create_story(title, slug, cover_url, author, category, description)
                if sb_enabled()
                else None
            )
            if sb_enabled() and not story_id:
                print("  ERROR: Could not get/create story")
                continue

            chapter_batches = chunk_chapters([ch for ch in comic["chapters"] if ch.get("sync_pending", True)])
            for batch in chapter_batches:
                r2_batch = []
                r2_ready: dict[float | int, bool] = {}
                for ch in batch:
                    if not ch.get("sync_pending", True):
                        continue
                    ch_num = ch["number"]
                    r2_prefix = f"chapters/{slug}/ch_{ch_num}"
                    if chapter_already_on_r2(ch, slug):
                        print(f"  [Skip] Ch {ch_num} already exists on R2 ({r2_prefix})")
                        r2_ready[ch_num] = True
                        continue
                    r2_batch.append(ch)

                if r2_batch:
                    with ThreadPoolExecutor(max_workers=R2_MAX_WORKERS) as ex:
                        futures = [
                            ex.submit(lambda ch=ch: (
                                upload_cbz_to_r2(ch["file"], f"chapters/{slug}/ch_{ch['number']}", compare_existing=True)
                                if ch["format"] == "cbz"
                                else upload_to_r2(ch["dir"], f"chapters/{slug}/ch_{ch['number']}", compare_existing=True)
                            )) for ch in r2_batch
                        ]
                        for ch, future in zip(r2_batch, futures):
                            upload_ok = future.result()
                            r2_ready[ch["number"]] = upload_ok
                            if not upload_ok:
                                print("  [ERROR] Upload failed in batch; dropping chapter from sync queue")
                                continue
                            items_seen += 1

                supabase_batch = []
                for ch in batch:
                    if not ch.get("sync_pending", True):
                        continue
                    if not r2_ready.get(ch["number"], False):
                        print(f"  [Skip] Ch {ch['number']} not confirmed on R2; skipping Supabase insert")
                        continue
                    if not sb_enabled() or DRY_RUN:
                        items_created += 1
                        if ch["format"] == "cbz":
                            print(f"  [DRY-RUN] Would insert ch {ch['number']} with CBZ URL")
                        else:
                            print(f"  [DRY-RUN] Would insert ch {ch['number']} with {len(ch['images'])} images")
                        continue
                    supabase_batch.append(ch)

                if supabase_batch:
                    with ThreadPoolExecutor(max_workers=SUPABASE_MAX_WORKERS) as ex:
                        futures = [
                            ex.submit(_supabase_upsert_chapter, ch, story_id, slug)
                            for ch in supabase_batch
                        ]
                        for ch, future in zip(supabase_batch, futures):
                            try:
                                future.result()
                                items_created += 1
                                print(f"  ✓ Ch {ch['number']} synced to Supabase")
                                item_info = {
                                    "comic": title,
                                    "author": author,
                                    "category": category,
                                    "chapter": ch["title"],
                                    "ch_num": ch["number"],
                                    "dir": ch["dir"] if ch["format"] == "images" else ch["file"],
                                }
                                summary.append(item_info)
                                synced_for_prune.append(item_info)
                                chapters_manifest = meta.setdefault("chapters", {})
                                if not isinstance(chapters_manifest, dict):
                                    chapters_manifest = {}
                                    meta["chapters"] = chapters_manifest
                                chapters_manifest[chapter_key(ch["number"])] = {
                                    "number": ch["number"],
                                    "title": ch["title"],
                                    "url": chapters_manifest.get(chapter_key(ch["number"]), {}).get("url", ""),
                                    "synced": True,
                                }
                                save_meta(meta_path, meta)
                            except Exception as e:
                                print(f"  ERROR inserting ch {ch['number']}: {e}", file=sys.stderr)

        # Backup & Prune
        drive_ok = backup_to_drive(downloads)
        if drive_ok and synced_for_prune:
            prune_local_chapters(synced_for_prune)
        elif not drive_ok:
            print("\n[Prune] Skipped pruning because Drive backup failed.")

        elapsed_sec = (datetime.now(timezone.utc) - started_at).total_seconds()

        # Record metrics in Supabase
        if sb_enabled():
            log_msg = f"Synced {len(summary)} chapters across {len(comics)} comics in {elapsed_sec:.1f}s"
            record_crawler_run(primary_source_id, started_at, items_seen, items_created, items_updated, log_msg, status="completed")

        # Discord Report
        print(f"\n{'=' * 40}")
        print(f"Total new chapters: {len(summary)} (completed in {elapsed_sec:.1f}s)")
        send_discord(summary, elapsed_sec)
        print("Discord notification sent")

    except Exception as e:
        err_msg = f"Fatal pipeline error: {e}"
        print(f"\n[FATAL] {err_msg}", file=sys.stderr)
        if sb_enabled():
            record_crawler_run(primary_source_id, started_at, items_seen, items_created, items_updated, err_msg, status="failed")
        raise


if __name__ == "__main__":
    main()
