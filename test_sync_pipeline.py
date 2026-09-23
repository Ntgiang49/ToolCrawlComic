import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import requests
import sync_pipeline as sp
from sync_pipeline import slugify, extract_chapter_number, scan_downloads, prune_local_chapters, backup_to_drive, build_discord_payload

class TestSyncPipelineHelpers(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("Solo Leveling"), "solo-leveling")
        self.assertEqual(slugify("Tomb Raider King!"), "tomb-raider-king")
        self.assertEqual(slugify("  Spaces   Around  "), "spaces-around")
        self.assertEqual(slugify("Võ Luyện Đỉnh Phong"), "võ-luyện-đỉnh-phong")

    def test_extract_chapter_number(self):
        self.assertEqual(extract_chapter_number("Chapter 001"), 1)
        self.assertEqual(extract_chapter_number("Ch. 12"), 12)
        self.assertEqual(extract_chapter_number("Chapter 012.5"), 12.5)
        self.assertEqual(extract_chapter_number("Chapter 000"), 0)
        self.assertEqual(extract_chapter_number("Chapter 0"), 0)
        self.assertEqual(extract_chapter_number("Vol. 1 Chapter 12"), 12)
        self.assertEqual(extract_chapter_number("Season 2 Ch 15"), 15)
        self.assertEqual(extract_chapter_number("Prologue"), None)

    def test_chunk_chapters_defaults_to_ten_per_batch(self):
        many = list(range(1, 26))
        batches = sp.chunk_chapters(many, 10)
        self.assertEqual(len(batches), 3)
        self.assertEqual(batches[0], list(range(1, 11)))
        self.assertEqual(batches[-1], list(range(21, 26)))

    def test_supabase_worker_limit_is_configured_separately(self):
        self.assertEqual(sp.R2_MAX_WORKERS, 4)
        self.assertEqual(sp.SUPABASE_MAX_WORKERS, 2)

    def test_retry_on_http_429_and_5xx_uses_exponential_backoff(self):
        calls = {"count": 0}

        def fake_get(url, **kwargs):
            calls["count"] += 1
            if calls["count"] < 3:
                resp = MagicMock()
                resp.status_code = 429 if calls["count"] == 1 else 500
                raise requests.HTTPError(response=resp)
            return {"ok": True}

        with patch("sync_pipeline.time.sleep") as mock_sleep:
            result = sp.with_retry(lambda: fake_get("https://example.com"), "test", max_retries=3)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(mock_sleep.call_count, 2)
        self.assertGreaterEqual(mock_sleep.call_args_list[0].args[0], 1.0)
        self.assertLess(mock_sleep.call_args_list[0].args[0], 2.0)
        self.assertGreaterEqual(mock_sleep.call_args_list[1].args[0], 2.0)


class TestScanDownloads(unittest.TestCase):
    def test_scan_marks_manifest_synced_chapter_as_not_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            comic_dir = Path(tmpdir) / "Manifest Comic"
            comic_dir.mkdir()
            (comic_dir / "meta.json").write_text(json.dumps({
                "chapters": {
                    "1": {"number": 1, "synced": True},
                    "2": {"number": 2, "synced": False},
                }
            }), encoding="utf-8")
            for number in (1, 2):
                chapter_dir = comic_dir / f"Chapter {number}"
                chapter_dir.mkdir()
                (chapter_dir / "001.jpg").write_bytes(b"image")

            chapters = scan_downloads(Path(tmpdir))[0]["chapters"]

            self.assertEqual(len(chapters), 1)
            self.assertEqual(chapters[0]["number"], 2)
            self.assertTrue(chapters[0]["sync_pending"])

    def test_scan_with_meta_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            comic_dir = Path(tmpdir) / "Test Comic"
            comic_dir.mkdir()
            meta = {
                "url": "https://nettruyen.gg/truyen/test-comic",
                "title": "Test Comic",
                "author": "Oda",
                "category": "Action, Shounen",
                "description": "Epic story"
            }
            (comic_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

            ch_dir = comic_dir / "Chapter 1"
            ch_dir.mkdir()
            (ch_dir / "001.jpg").write_bytes(b"image content")

            comics = scan_downloads(Path(tmpdir))
            self.assertEqual(len(comics), 1)
            c = comics[0]
            self.assertEqual(c["title"], "Test Comic")
            self.assertEqual(c["author"], "Oda")
            self.assertEqual(c["category"], "Action, Shounen")
            self.assertEqual(c["description"], "Epic story")
            self.assertEqual(c["url"], "https://nettruyen.gg/truyen/test-comic")
            self.assertEqual(len(c["chapters"]), 1)
            self.assertEqual(c["chapters"][0]["number"], 1)

    def test_scan_cbz_chapter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            comic_dir = Path(tmpdir) / "CBZ Comic"
            comic_dir.mkdir()
            cbz_file = comic_dir / "Chapter 001.cbz"
            cbz_file.write_bytes(b"mock-cbz")

            comics = scan_downloads(Path(tmpdir))

            self.assertEqual(len(comics), 1)
            chapter = comics[0]["chapters"][0]
            self.assertEqual(chapter["number"], 1)
            self.assertEqual(chapter["format"], "cbz")
            self.assertEqual(chapter["file"], cbz_file)


class TestSupabaseOperations(unittest.TestCase):
    def test_sb_enabled_false_when_no_keys(self):
        sp.SUPABASE_URL = ""
        sp.SUPABASE_KEY = ""
        self.assertFalse(sp.sb_enabled())

    def test_sb_enabled_true_when_keys(self):
        sp.SUPABASE_URL = "https://x.supabase.co"
        sp.SUPABASE_KEY = "k"
        self.assertTrue(sp.sb_enabled())

    def test_dry_run_entity_creation(self):
        saved_dry = sp.DRY_RUN
        try:
            sp.DRY_RUN = True
            self.assertEqual(sp.get_or_create_author("Oda"), "dry-run-author-id")
            self.assertEqual(sp.get_or_create_category("Action, Adventure"), "dry-run-category-id")
            self.assertEqual(sp.get_or_create_genre("Shounen"), "dry-run-genre-id")
            self.assertEqual(sp.get_or_create_crawler_source("https://example.com/comic/1"), "dry-run-source-id")
            self.assertEqual(sp.get_or_create_story("Title", "title", None, "Oda", "Action", "Desc"), "dry-run-id")
        finally:
            sp.DRY_RUN = saved_dry

    @patch("sync_pipeline.supabase_get")
    def test_get_existing_chapter_numbers_pagination(self, mock_get):
        sp.SUPABASE_URL = "https://x.supabase.co"
        sp.SUPABASE_KEY = "key"
        sp.DRY_RUN = False

        page1 = [{"chapter_number": i} for i in range(1, 1001)]
        page2 = [{"chapter_number": i} for i in range(1001, 1050)]
        mock_get.side_effect = [page1, page2]

        chapters = sp.get_existing_chapter_numbers("story-123")
        self.assertEqual(len(chapters), 1049)
        self.assertIn(1, chapters)
        self.assertIn(1000, chapters)
        self.assertIn(1049, chapters)
        self.assertEqual(mock_get.call_count, 2)


class TestBackupAndPrune(unittest.TestCase):
    def test_backup_skip_flag(self):
        saved_skip = sp.SKIP_BACKUP
        try:
            sp.SKIP_BACKUP = True
            self.assertTrue(backup_to_drive(Path("dummy")))
        finally:
            sp.SKIP_BACKUP = saved_skip

    def test_prune_local_chapters_live(self):
        saved_prune = sp.PRUNE_ENABLED
        saved_dry = sp.DRY_RUN
        try:
            sp.PRUNE_ENABLED = True
            sp.DRY_RUN = False
            with tempfile.TemporaryDirectory() as tmpdir:
                comic_dir = Path(tmpdir) / "Comic"
                ch_dir = comic_dir / "Chapter 1"
                ch_dir.mkdir(parents=True)
                (ch_dir / "001.jpg").write_bytes(b"test")

                self.assertTrue(ch_dir.exists())
                prune_local_chapters([{"dir": ch_dir}])
                self.assertFalse(ch_dir.exists())
        finally:
            sp.PRUNE_ENABLED = saved_prune
            sp.DRY_RUN = saved_dry


class TestDiscordPayload(unittest.TestCase):
    def test_payload_empty_summary(self):
        payload = build_discord_payload([])
        desc = payload["embeds"][0]["description"]
        self.assertIn("No new chapters", desc)

    def test_payload_groups_by_comic_with_author_and_category(self):
        payload = build_discord_payload([
            {"comic": "One Piece", "author": "Oda", "category": "Shounen", "chapter": "1120"},
            {"comic": "One Piece", "author": "Oda", "category": "Shounen", "chapter": "1121"},
            {"comic": "Jujutsu Kaisen", "author": "Gege", "category": "Action", "chapter": "268"},
        ])
        fields = {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}
        self.assertTrue(any("One Piece" in k and "Oda" in k and "Shounen" in k for k in fields.keys()))
        self.assertTrue(any("1120, 1121" in v for v in fields.values()))
        self.assertEqual(len(fields), 2)

    def test_payload_reports_count(self):
        payload = build_discord_payload([{"comic": "A", "author": "Unknown", "chapter": "Ch 1"}])
        self.assertIn("1 new chapter(s)", payload["embeds"][0]["description"])

    def test_payload_reports_duration(self):
        payload = build_discord_payload([{"comic": "A", "author": "Unknown", "chapter": "Ch 1"}], duration_seconds=12.4)
        footer = payload["embeds"][0]["footer"]["text"]
        self.assertIn("12.4s", footer)


class TestR2Operations(unittest.TestCase):
    def test_get_existing_r2_keys_pagination(self):
        mock_client = MagicMock()
        mock_client.list_objects_v2.side_effect = [
            {
                "Contents": [{"Key": "chapters/comic/ch_1/001.jpg"}, {"Key": "chapters/comic/ch_1/002.jpg"}],
                "IsTruncated": True,
                "NextContinuationToken": "token-123"
            },
            {
                "Contents": [{"Key": "chapters/comic/ch_1/003.jpg"}],
                "IsTruncated": False
            }
        ]

        keys = sp.get_existing_r2_keys(mock_client, "chapters/comic/ch_1")
        self.assertEqual(len(keys), 3)
        self.assertIn("chapters/comic/ch_1/001.jpg", keys)
        self.assertIn("chapters/comic/ch_1/002.jpg", keys)
        self.assertIn("chapters/comic/ch_1/003.jpg", keys)
        self.assertEqual(mock_client.list_objects_v2.call_count, 2)

    def test_upload_to_r2_with_webp_headers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ch_dir = Path(tmpdir) / "Chapter 1"
            ch_dir.mkdir()
            img_file = ch_dir / "001.webp"
            img_file.write_bytes(b"mock-webp-bytes")

            mock_client = MagicMock()
            mock_client.list_objects_v2.return_value = {"Contents": []}

            with patch("sync_pipeline._get_r2_client", return_value=mock_client):
                success = sp.upload_to_r2(ch_dir, "chapters/test/ch_1")
                self.assertTrue(success)
                mock_client.upload_file.assert_called_once()
                args, kwargs = mock_client.upload_file.call_args
                self.assertEqual(kwargs["ExtraArgs"]["ContentType"], "image/webp")

    def test_upload_cbz_to_r2_with_archive_headers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cbz_file = Path(tmpdir) / "Chapter 001.cbz"
            cbz_file.write_bytes(b"mock-cbz-bytes")

            mock_client = MagicMock()
            mock_client.list_objects_v2.return_value = {"Contents": []}

            with patch("sync_pipeline._get_r2_client", return_value=mock_client):
                success = sp.upload_cbz_to_r2(cbz_file, "chapters/test/ch_1")

            self.assertTrue(success)
            mock_client.upload_file.assert_called_once()
            args, kwargs = mock_client.upload_file.call_args
            self.assertEqual(args[2], "chapters/test/ch_1/Chapter 001.cbz")
            self.assertEqual(kwargs["ExtraArgs"]["ContentType"], "application/vnd.comicbook+zip")
class TestHealthCheck(unittest.TestCase):
    def test_run_health_check_healthy(self):
        mock_r2 = MagicMock()
        mock_r2.head_bucket.return_value = {}

        with patch("sync_pipeline._get_r2_client", return_value=mock_r2), \
             patch("sync_pipeline.supabase_get", return_value=[{"id": "123"}]), \
             patch("sync_pipeline.shutil.which", return_value="/usr/bin/rclone"), \
             patch("sync_pipeline.DISCORD_WEBHOOK", "https://discord.com/api/webhooks/123/abc"):
            healthy = sp.run_health_check()
            self.assertTrue(healthy)


if __name__ == '__main__':
    unittest.main()
