#!/usr/bin/env python3
"""Sync pipeline: scan downloads → upload R2 → upsert Supabase → Discord notify."""

import boto3
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', write_through=True)

import requests

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
DRY_RUN = "--dry-run" in sys.argv

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def sb_enabled() -> bool:
    """Supabase DB ops only when URL + service key present."""
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
    """Extract integer chapter number from folder name.

    'Chapter 001' → 1, 'Ch.12.5' → 12 (truncated), 'Prologue' → None.
    Returns None if <= 0 or unparseable.
    """
    # ponytail: truncate decimals to int. DB column is integer.
    # Trade-off: Chapter 12.5 stored as 12. ON CONFLICT skips if 12 exists.
    match = re.search(r"(\d+)", folder_name)
    if match:
        num = int(match.group(1))
        return num if num > 0 else None
    return None


def scan_downloads(downloads: Path) -> list[dict]:
    """Scan downloads/ for comics and chapters. Returns structured data."""
    comics = []
    for comic_dir in sorted(downloads.iterdir()):
        if not comic_dir.is_dir() or comic_dir.name.startswith("_"):
            continue

        title = comic_dir.name
        slug = slugify(title)
        author = "Unknown"
        meta_path = comic_dir / "meta.json"
        if meta_path.is_file():
            try:
                author = json.loads(meta_path.read_text(encoding="utf-8")).get("author", "Unknown")
            except (json.JSONDecodeError, OSError):
                pass
        chapters = []

        for ch_dir in sorted(comic_dir.iterdir()):
            if not ch_dir.is_dir():
                continue
            ch_num = extract_chapter_number(ch_dir.name)
            if ch_num is None:
                print(f"  Skipping (no valid number): {ch_dir.name}")
                continue
            images = sorted(
                f for f in ch_dir.iterdir() if f.suffix.lower() in IMAGE_EXTS
            )
            if not images:
                print(f"  Skipping (empty): {ch_dir.name}")
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
                {"title": title, "slug": slug, "author": author, "dir": comic_dir, "chapters": chapters}
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
        f"{SUPABASE_URL}/rest/v1/{table}", headers=_sb_headers(), params=params,
        timeout=30,
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


def get_or_create_story(
    title: str, slug: str, cover_url: str | None, author: str = "AutoCrawler"
) -> str | None:
    """Get existing story ID by slug, or create new. Returns UUID string."""
    existing = supabase_get("stories", {"slug": f"eq.{slug}", "select": "id"})
    if existing:
        return existing[0]["id"]

    if DRY_RUN:
        print(f"  [DRY-RUN] Would create story: {title} ({slug})")
        return "dry-run-id"

    try:
        result = supabase_post(
            "stories",
            {
                "title": title,
                "slug": slug,
                "status": "published",
                "author": author,
                "cover_url": cover_url,
            },
        )
        return result[0]["id"] if result else None
    except requests.HTTPError as e:
        # Slug conflict → append deterministic hash
        if e.response is not None and e.response.status_code == 409:
            import hashlib

            hash_suffix = hashlib.md5(title.encode()).hexdigest()[:6]
            new_slug = f"{slug}-{hash_suffix}"
            print(f"  Slug conflict, retrying with: {new_slug}")
            result = supabase_post(
                "stories",
                {
                    "title": title,
                    "slug": new_slug,
                    "status": "published",
                    "author": author,
                    "cover_url": cover_url,
                },
            )
            return result[0]["id"] if result else None
        raise


def chapter_exists(story_id: str, chapter_number: int) -> bool:
    result = supabase_get(
        "chapters",
        {
            "story_id": f"eq.{story_id}",
            "chapter_number": f"eq.{chapter_number}",
            "select": "id",
        },
    )
    return len(result) > 0


# ── R2 Upload ────────────────────────────────────────────────────────


# ponytail: head_object skip → reruns cheap; costs 1 HEAD per image per run.
# Upgrade path: batch list_objects once per prefix if image counts grow 10x.
def upload_to_r2(local_dir: Path, r2_prefix: str) -> bool:
    """Upload chapter images to R2 via boto3 (credentials from env)."""
    endpoint = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    if DRY_RUN:
        print(f"  [DRY-RUN] Would upload {local_dir} to s3://{R2_BUCKET}/{r2_prefix}")
        return True
    client = boto3.session.Session().client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    )
    try:
        for img in local_dir.iterdir():
            if not img.is_file():
                continue
            key = f"{r2_prefix}/{img.name}"
            try:
                client.head_object(Bucket=R2_BUCKET, Key=key)
                continue  # already uploaded
            except client.exceptions.ClientError:
                pass
            client.upload_file(str(img), R2_BUCKET, key)
    except Exception as e:
        print(f"  ERROR uploading: {e}", file=sys.stderr)
        return False
    return True


# ── Discord ──────────────────────────────────────────────────────────


def build_discord_payload(summary: list[dict]) -> dict:
    """Pure Discord embed payload from sync summary."""
    comics: dict[str, list[str]] = {}
    for item in summary:
        comics.setdefault(item["comic"], []).append(item["chapter"])

    fields = []
    for name, chapters in list(comics.items())[:20]:
        fields.append(
            {"name": name, "value": ", ".join(chapters[:10]), "inline": False}
        )

    if summary:
        description = f"Uploaded {len(summary)} new chapter(s)"
    else:
        description = "No new chapters today"

    return {
        "embeds": [
            {
                "title": "📚 Comic Crawler Report",
                "description": description,
                "color": 5763719,
                "fields": fields,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }


def send_discord(summary: list[dict]) -> None:
    """Send Discord webhook with upload summary (always sends, even empty)."""
    if not DISCORD_WEBHOOK:
        print("DISCORD_WEBHOOK_URL not set, skipping notification")
        return

    payload = build_discord_payload(summary)

    if DRY_RUN:
        print(f"[DRY-RUN] Discord payload:\n{json.dumps(payload, indent=2)}")
        return

    resp = requests.post(DISCORD_WEBHOOK, json=payload, timeout=30)
    if resp.status_code not in (200, 204):
        print(
            f"Discord webhook failed: {resp.status_code} {resp.text}",
            file=sys.stderr,
        )


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
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

    for comic in comics:
        title = comic["title"]
        slug = comic["slug"]
        print(f"\n{'─' * 40}")
        print(f"Comic: {title} (slug: {slug})")

        # Cover URL = first image of first chapter
        first_ch = comic["chapters"][0]
        cover_url = (
            f"{R2_PUBLIC_URL}/chapters/{slug}"
            f"/ch_{first_ch['number']}/{first_ch['images'][0].name}"
        )

        # ponytail: no Supabase → dedupe relies on aws s3 sync idempotence +
        # local skip-existing. Ceiling: re-upload if R2 objects deleted.
        story_id = get_or_create_story(title, slug, cover_url, comic["author"]) if sb_enabled() else None
        if sb_enabled() and not story_id:
            print("  ERROR: Could not get/create story")
            continue

        for ch in comic["chapters"]:
            ch_num = ch["number"]

            # Check DB first (source of truth)
            if sb_enabled() and not DRY_RUN and chapter_exists(story_id, ch_num):
                continue  # silent skip — expected for existing chapters

            r2_prefix = f"chapters/{slug}/ch_{ch_num}"

            # Upload images to R2
            print(f"  Uploading ch {ch_num} ({len(ch['images'])} images)...")
            if not upload_to_r2(ch["dir"], r2_prefix):
                print(f"  ERROR: Upload failed for ch {ch_num}")
                continue

            # Build content array (full public URLs)
            content = json.dumps(
                [
                    f"{R2_PUBLIC_URL}/{r2_prefix}/{img.name}"
                    for img in ch["images"]
                ]
            )

            # Insert chapter
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
                    print(f"  ✓ Ch {ch_num} synced")
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 409:
                        pass  # already exists, fine
                    else:
                        print(f"  ERROR inserting ch {ch_num}: {e}", file=sys.stderr)
                        continue
            else:
                print(
                    f"  [DRY-RUN] Would insert ch {ch_num}"
                    f" with {len(ch['images'])} images"
                )

            summary.append({"comic": title, "chapter": ch["title"]})

    # Report
    print(f"\n{'=' * 40}")
    print(f"Total new chapters: {len(summary)}")

    send_discord(summary)
    print("Discord notification sent")


if __name__ == "__main__":
    main()
