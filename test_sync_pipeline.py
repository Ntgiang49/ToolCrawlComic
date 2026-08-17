import unittest
import sync_pipeline as sp
from sync_pipeline import slugify, extract_chapter_number

class TestSyncPipelineHelpers(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("Solo Leveling"), "solo-leveling")
        self.assertEqual(slugify("Tomb Raider King!"), "tomb-raider-king")
        self.assertEqual(slugify("  Spaces   Around  "), "spaces-around")
        self.assertEqual(slugify("Võ Luyện Đỉnh Phong"), "võ-luyện-đỉnh-phong")

    def test_extract_chapter_number(self):
        self.assertEqual(extract_chapter_number("Chapter 001"), 1)
        self.assertEqual(extract_chapter_number("Ch. 12"), 12)
        self.assertEqual(extract_chapter_number("Chapter 012.5"), 12) # Truncates decimal
        self.assertEqual(extract_chapter_number("Prologue"), None)
        self.assertEqual(extract_chapter_number("Chapter 000"), None)


class TestSupabaseOptional(unittest.TestCase):
    def test_sb_enabled_false_when_no_keys(self):
        sp.SUPABASE_URL = ""
        sp.SUPABASE_KEY = ""
        self.assertFalse(sp.sb_enabled())

    def test_sb_enabled_true_when_keys(self):
        sp.SUPABASE_URL = "https://x.supabase.co"
        sp.SUPABASE_KEY = "k"
        self.assertTrue(sp.sb_enabled())


class TestDiscordPayload(unittest.TestCase):
    def test_payload_empty_summary(self):
        payload = sp.build_discord_payload([])
        desc = payload["embeds"][0]["description"]
        self.assertEqual(desc, "No new chapters today")

    def test_payload_groups_by_comic(self):
        payload = sp.build_discord_payload([
            {"comic": "A", "chapter": "Ch 1"},
            {"comic": "A", "chapter": "Ch 2"},
            {"comic": "B", "chapter": "Ch 1"},
        ])
        fields = {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}
        self.assertEqual(fields["A"], "Ch 1, Ch 2")
        self.assertEqual(fields["B"], "Ch 1")

    def test_payload_reports_count(self):
        payload = sp.build_discord_payload([{"comic": "A", "chapter": "Ch 1"}])
        self.assertEqual(payload["embeds"][0]["description"], "Uploaded 1 new chapter(s)")

if __name__ == '__main__':
    unittest.main()
