#!/usr/bin/env python3
"""Sync pipeline: scan downloads → upload R2 (batch listed) → upsert Supabase (batch queried) → Drive backup → auto-prune → Discord notify."""

import io
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

if sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', write_through=True)

import boto3
import requests
from tqdm import tqdm

# --- Config from env ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
R2_BUCKET = os.environ.get("R2_BUCKET_NAME", "comic")
R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_PUBLIC_URL = os.environ.get(
    "R2_PUBLIC_URL",
    "https://pub-006586cb2a0d4198bcd302b9b8f8ea45.r2.dev",
)
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
DOWNLOADS_DIR = os.environ.get("DOWNLOADS_DIR", "downloads")
RCLONE_REMOTE = os.environ.get("RCLONE_REMOTE", "gdrive:Comic")

# CLI flags
DRY_RUN = "--dry-run" in sys.argv
SKIP_BACKUP = "--skip-backup" in sys.argv
PRUNE_ENABLED = "--prune" in sys.argv

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


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


def extract_chapter_number(folder_name: str) -> int | None:
    """Extract integer chapter number from folder name ('Chapter 001' → 1)."""
    match = re.search(r"(\d+)", folder_name)
    if match:
        num = int(match.group(1))
        return num if num > 0 else None
    return None


def scan_downloads(downloads: Path) -> list[dict]:
    """Scan downloads folder for comics and chapters with metadata."""
    comics = []
    for comic_dir in sorted(downloads.iterdir()):
        if not comic_dir.is_dir() or comic_dir.name.startswith("_"):
            continue

        title = comic_dir.name
        slug = slugify(title)
        meta = {}
        meta_path = comic_dir / "meta.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        chapters = []
        for ch_dir in sorted(comic_dir.iterdir()):
            if not ch_dir.is_dir() or ch_dir.name.startswith("_"):
                continue
            ch_num = extract_chapter_number(ch_dir.name)
            if ch_num is None:
                continue
            images = sorted(
                f for f in ch_dir.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS
            )
            if not images:
                continue
            chapters.append(
                {
                    "dir": ch_dir,
                    "number": ch_num,
                    "title": ch_dir.name,
                    "images": images,
                }
            )

        if chapters:
            comics.append(
                {
                    "title": title,
                    "slug": slug,
                    "author": meta.get("author", "Unknown"),
                    "category": meta.get("category", "Unknown"),
                    "description": meta.get("description", ""),
                    "url": meta.get("url", ""),
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


def _get_or_create_named_row(table: str, name: str, dry_run_id: str) -> str | None:
    """Helper to get or insert a row by name in a lookup table (authors, categories, genres)."""
    clean_name = name.strip()
    if not clean_name or clean_name == "Unknown":
        return None
    if DRY_RUN:
        return dry_run_id
    if not sb_enabled():
        return None
    try:
        existing = supabase_get(table, {"name": f"eq.{clean_name}", "select": "id"})
        if existing:
            return existing[0]["id"]
        res = supabase_post(table, {"name": clean_name})
        return res[0]["id"] if res else None
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
                "source_type": "comic",
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
    status: str = "completed",
) -> None:
    """Record execution metrics in crawler_runs table."""
    if not sb_enabled() or DRY_RUN:
        return
    try:
        supabase_post(
            "crawler_runs",
            {
                "source_id": source_id,
                "status": status,
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "items_seen": items_seen,
                "items_created": items_created,
                "items_updated": items_updated,
                "log": log_text[:5000] if log_text else "Sync completed successfully",
            },
        )
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


def get_existing_chapter_numbers(story_id: str) -> set[int]:
    """Batch fetch all existing chapter numbers for a story in 1 query."""
    if not sb_enabled() or DRY_RUN or not story_id:
        return set()
    try:
        res = supabase_get("chapters", {"story_id": f"eq.{story_id}", "select": "chapter_number"})
        return {int(r["chapter_number"]) for r in res if "chapter_number" in r and r["chapter_number"] is not None}
    except Exception as e:
        print(f"  [Warning] Failed to batch fetch existing chapters: {e}", file=sys.stderr)
        return set()


# ── R2 Upload ────────────────────────────────────────────────────────


def get_existing_r2_keys(client, prefix: str) -> set[str]:
    """Fetch all existing object keys under prefix in 1 list_objects_v2 call."""
    try:
        resp = client.list_objects_v2(Bucket=R2_BUCKET, Prefix=prefix)
        if "Contents" in resp:
            return {obj["Key"] for obj in resp["Contents"]}
    except Exception:
        pass
    return set()


def upload_to_r2(local_dir: Path, r2_prefix: str) -> bool:
    """Upload chapter images to R2 with tqdm byte progress bar."""
    if DRY_RUN:
        print(f"  [DRY-RUN] Would upload {local_dir} to s3://{R2_BUCKET}/{r2_prefix}")
        return True

    endpoint = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    client = boto3.session.Session().client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    )
    try:
        imgs = sorted([p for p in local_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS])
        if not imgs:
            return True

        existing_keys = get_existing_r2_keys(client, r2_prefix)
        to_upload = [img for img in imgs if f"{r2_prefix}/{img.name}" not in existing_keys]

        if not to_upload:
            print(f"  All {len(imgs)} images already in R2 (skipped)")
            return True

        total_bytes = sum(p.stat().st_size for p in to_upload)

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
                client.upload_file(
                    str(img),
                    R2_BUCKET,
                    key,
                    Callback=lambda b: pbar.update(b),
                )

            with ThreadPoolExecutor(max_workers=8) as ex:
                list(ex.map(_upload, to_upload))

        print(f"  ✓ Uploaded {len(to_upload)}/{len(imgs)} image(s) ({total_bytes / (1024 * 1024):.1f} MB)")
    except Exception as e:
        print(f"  ERROR uploading: {e}", file=sys.stderr)
        return False
    return True


# ── Backup & Prune ───────────────────────────────────────────────────


def backup_to_drive(downloads_dir: Path) -> bool:
    """Run rclone copy to backup downloads to Google Drive."""
    if SKIP_BACKUP:
        print("\n[Drive] Backup skipped (--skip-backup)")
        return True

    if not shutil.which("rclone"):
        print("\n[Drive] Warning: 'rclone' executable not found in PATH. Skipping Drive backup.")
        return True

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
            timeout=600,
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
    """Prune local chapter directories after confirmed R2 and Drive sync."""
    if not PRUNE_ENABLED:
        return

    print(f"\n[Prune] Pruning {len(synced_chapters)} synced chapter folder(s)...")
    pruned_count = 0
    freed_bytes = 0

    for item in synced_chapters:
        ch_dir = item.get("dir")
        if not ch_dir or not ch_dir.exists() or not ch_dir.is_dir():
            continue

        dir_size = sum(f.stat().st_size for f in ch_dir.iterdir() if f.is_file())
        file_count = len([f for f in ch_dir.iterdir() if f.is_file()])

        if DRY_RUN:
            print(f"  [DRY-RUN] Would prune: {ch_dir.parent.name}/{ch_dir.name} ({file_count} files, {dir_size / (1024 * 1024):.1f} MB)")
        else:
            try:
                shutil.rmtree(ch_dir)
                print(f"  ✓ Pruned: {ch_dir.parent.name}/{ch_dir.name} ({file_count} files, {dir_size / (1024 * 1024):.1f} MB)")
            except Exception as e:
                print(f"  [Warning] Failed to prune {ch_dir}: {e}", file=sys.stderr)
                continue

        pruned_count += 1
        freed_bytes += dir_size

    print(f"  Pruning summary: {pruned_count} folder(s) removed, {freed_bytes / (1024 * 1024):.1f} MB freed.")


# ── Discord ──────────────────────────────────────────────────────────


def build_discord_payload(summary: list[dict]) -> dict:
    """Rich Discord embed payload from sync summary."""
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

    return {
        "embeds": [
            {
                "title": "📚 Comic Crawler & Sync Report",
                "description": f"🚀 **Uploaded {len(summary)} new chapter(s)** across **{len(comics_map)} comic(s)**" if summary else "😴 No new chapters synced today",
                "color": 3066993 if summary else 9807270,
                "fields": fields,
                "footer": {"text": "Comic Crawler Easy • R2 + Supabase"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }


def send_discord(summary: list[dict]) -> None:
    """Send Discord webhook notification."""
    if not DISCORD_WEBHOOK:
        print("DISCORD_WEBHOOK_URL not set, skipping notification")
        return

    payload = build_discord_payload(summary)
    if DRY_RUN:
        print(f"\n[DRY-RUN] Discord payload:\n{json.dumps(payload, indent=2, ensure_ascii=False)}")
        return

    resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=30)
    if resp.status_code not in (200, 204):
        print(f"Discord webhook failed: {resp.status_code} {resp.text}", file=sys.stderr)


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    started_at = datetime.now(timezone.utc)
    downloads = Path(DOWNLOADS_DIR)
    if not downloads.exists():
        print(f"Downloads directory not found: {downloads}")
        sys.exit(0)

    if DRY_RUN:
        print("=== DRY RUN MODE ===\n")

    comics = scan_downloads(downloads)
    if not comics:
        print("No comics found in downloads/")
        sys.exit(0)

    summary: list[dict] = []
    synced_for_prune: list[dict] = []
    items_seen = 0
    items_created = 0
    items_updated = 0
    primary_source_id = None

    try:
        for comic in comics:
            title = comic["title"]
            slug = comic["slug"]
            author = comic["author"]
            category = comic["category"]
            description = comic["description"]
            url = comic["url"]

            if url and not primary_source_id and sb_enabled():
                primary_source_id = get_or_create_crawler_source(url)

            print(f"\n{'─' * 40}")
            print(f"Comic: {title} (slug: {slug})")
            if author and author != "Unknown":
                print(f"  Author: {author}")
            if category and category != "Unknown":
                print(f"  Category: {category}")

            first_ch = comic["chapters"][0]
            cover_url = f"{R2_PUBLIC_URL}/chapters/{slug}/ch_{first_ch['number']}/{first_ch['images'][0].name}"

            story_id = (
                get_or_create_story(title, slug, cover_url, author, category, description)
                if sb_enabled()
                else None
            )
            if sb_enabled() and not story_id:
                print("  ERROR: Could not get/create story")
                continue

            existing_chapters = get_existing_chapter_numbers(story_id) if (sb_enabled() and not DRY_RUN) else set()

            for ch in comic["chapters"]:
                items_seen += 1
                ch_num = ch["number"]

                if ch_num in existing_chapters:
                    continue

                r2_prefix = f"chapters/{slug}/ch_{ch_num}"

                print(f"  Uploading ch {ch_num} ({len(ch['images'])} images)...")
                if not upload_to_r2(ch["dir"], r2_prefix):
                    print(f"  ERROR: Upload failed for ch {ch_num}")
                    continue

                content = json.dumps([f"{R2_PUBLIC_URL}/{r2_prefix}/{img.name}" for img in ch["images"]])

                if sb_enabled() and not DRY_RUN:
                    try:
                        supabase_post(
                            "chapters",
                            {
                                "story_id": story_id,
                                "chapter_number": ch_num,
                                "title": ch["title"],
                                "content": content,
                                "status": "published",
                                "published_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                        items_created += 1
                        print(f"  ✓ Ch {ch_num} synced to Supabase")
                    except requests.HTTPError as e:
                        if e.response is None or e.response.status_code != 409:
                            print(f"  ERROR inserting ch {ch_num}: {e}", file=sys.stderr)
                            continue
                else:
                    items_created += 1
                    print(f"  [DRY-RUN] Would insert ch {ch_num} with {len(ch['images'])} images")

                item_info = {
                    "comic": title,
                    "author": author,
                    "category": category,
                    "chapter": ch["title"],
                    "ch_num": ch_num,
                    "dir": ch["dir"],
                }
                summary.append(item_info)
                synced_for_prune.append(item_info)

        # Backup & Prune
        drive_ok = backup_to_drive(downloads)
        if drive_ok and synced_for_prune:
            prune_local_chapters(synced_for_prune)
        elif not drive_ok:
            print("\n[Prune] Skipped pruning because Drive backup failed.")

        # Record metrics in Supabase
        if sb_enabled():
            log_msg = f"Synced {len(summary)} chapters across {len(comics)} comics"
            record_crawler_run(primary_source_id, started_at, items_seen, items_created, items_updated, log_msg, status="completed")

        # Discord Report
        print(f"\n{'=' * 40}")
        print(f"Total new chapters: {len(summary)}")
        send_discord(summary)
        print("Discord notification sent")

    except Exception as e:
        err_msg = f"Fatal pipeline error: {e}"
        print(f"\n[FATAL] {err_msg}", file=sys.stderr)
        if sb_enabled():
            record_crawler_run(primary_source_id, started_at, items_seen, items_created, items_updated, err_msg, status="failed")
        raise


if __name__ == "__main__":
    main()
