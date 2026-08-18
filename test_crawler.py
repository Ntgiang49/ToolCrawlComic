import unittest
import os
import tempfile
from unittest.mock import patch, MagicMock
from PIL import Image

from comic_crawler.utils import sanitize_filename, make_absolute_url, extract_domain
from comic_crawler.config_loader import ConfigLoader
from comic_crawler.exporter import ComicExporter
from comic_crawler.core import ComicCrawler

class TestComicCrawler(unittest.TestCase):
    def test_utils(self):
        self.assertEqual(sanitize_filename("Comic: <Title> / Test?"), "Comic Title Test")
        self.assertEqual(extract_domain("https://sub.domain.com/path"), "sub.domain.com")
        self.assertEqual(make_absolute_url("https://site.com/ch1/", "page1.jpg"), "https://site.com/ch1/page1.jpg")

    def test_config_loader(self):
        loader = ConfigLoader()
        site_cfg = loader.get_site_config("https://asuracomic.net/series/test-123")
        self.assertIn("headers", site_cfg)
        self.assertIn("selectors", site_cfg)
        self.assertIn("author", site_cfg["selectors"])
        self.assertIn("category", site_cfg["selectors"])
        self.assertIn("description", site_cfg["selectors"])

    def test_config_loader_fallbacks(self):
        loader = ConfigLoader()
        fallback_cfg = loader.get_site_config("https://unlisted-site.com/comic/123")
        self.assertIn("author", fallback_cfg["selectors"])
        self.assertIn("category", fallback_cfg["selectors"])
        self.assertIn("description", fallback_cfg["selectors"])

    def test_parse_comic_info_mocked(self):
        crawler = ComicCrawler()
        sample_html = """
        <html>
            <head><title>Test Comic</title></head>
            <body>
                <h1 class="title-detail">My Awesome Comic</h1>
                <li class="author">Tác giả: Oda Sensei</li>
                <li class="kind"><a>Action</a><a>Adventure</a></li>
                <div class="detail-content"><p>An epic adventure in a fantasy world.</p></div>
                <div class="list-chapter">
                    <a href="/truyen-tranh/test/chuong-2">Chapter 2</a>
                    <a href="/truyen-tranh/test/chuong-1">Chapter 1</a>
                </div>
            </body>
        </html>
        """
        with patch.object(crawler, "_fetch_html", return_value=sample_html):
            info = crawler.parse_comic_info("https://nettruyen.gg/truyen-tranh/test")
            self.assertEqual(info["title"], "My Awesome Comic")
            self.assertEqual(info["author"], "Oda Sensei")
            self.assertIn("Action", info["category"])
            self.assertIn("Adventure", info["category"])
            self.assertEqual(info["description"], "An epic adventure in a fantasy world.")
            self.assertEqual(len(info["chapters"]), 2)
            self.assertEqual(info["chapters"][0]["title"], "Chapter 001")
            self.assertEqual(info["chapters"][1]["title"], "Chapter 002")

    def test_extract_chapter_images_mocked(self):
        crawler = ComicCrawler()
        sample_chapter_html = """
        <html>
            <body>
                <div class="reading-detail">
                    <img data-original="https://cdn.site.com/001.jpg" />
                    <img data-src="https://cdn.site.com/002.jpg" />
                    <img src="https://cdn.site.com/003.jpg" />
                </div>
            </body>
        </html>
        """
        loader = ConfigLoader()
        site_cfg = loader.get_site_config("https://nettruyen.gg/truyen/test")
        with patch.object(crawler, "_fetch_html", return_value=sample_chapter_html):
            images = crawler.extract_chapter_images("https://nettruyen.gg/truyen/test/chuong-1", site_cfg)
            self.assertEqual(len(images), 3)
            self.assertIn("https://cdn.site.com/001.jpg", images)
            self.assertIn("https://cdn.site.com/002.jpg", images)
            self.assertIn("https://cdn.site.com/003.jpg", images)

    def test_exporter_cbz_and_pdf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img_paths = []
            for i in range(2):
                img_path = os.path.join(tmpdir, f"img_{i}.jpg")
                img = Image.new("RGB", (100, 100), color="red")
                img.save(img_path)
                img_paths.append(img_path)

            cbz_out = os.path.join(tmpdir, "test.cbz")
            pdf_out = os.path.join(tmpdir, "test.pdf")

            ComicExporter.export_to_cbz(img_paths, cbz_out)
            self.assertTrue(os.path.exists(cbz_out))
            self.assertGreater(os.path.getsize(cbz_out), 0)

            ComicExporter.export_to_pdf(img_paths, pdf_out)
            self.assertTrue(os.path.exists(pdf_out))
            self.assertGreater(os.path.getsize(pdf_out), 0)

    def test_is_chapter_downloaded(self):
        crawler = ComicCrawler()
        with tempfile.TemporaryDirectory() as tmpdir:
            ch_name = "Chapter 001"
            cbz_path = os.path.join(tmpdir, "Chapter 001.cbz")
            
            # 1. Verify not downloaded yet
            is_dl, _ = crawler.is_chapter_downloaded(ch_name, tmpdir, "cbz")
            self.assertFalse(is_dl)

            # 2. Create dummy file
            with open(cbz_path, "wb") as f:
                f.write(b"dummy zip content")

            # 3. Verify detected as downloaded
            is_dl2, _ = crawler.is_chapter_downloaded(ch_name, tmpdir, "cbz")
            self.assertTrue(is_dl2)

if __name__ == "__main__":
    unittest.main()
