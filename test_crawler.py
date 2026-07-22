import unittest
import os
import tempfile
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
