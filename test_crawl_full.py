import unittest
from unittest.mock import patch, MagicMock
import requests

import crawl_full

class TestCrawlFull(unittest.TestCase):
    def test_imports_and_constants(self):
        self.assertTrue(hasattr(crawl_full, "ThreadPoolExecutor"))
        self.assertTrue(hasattr(crawl_full, "enumerate_valid"))
        self.assertTrue(hasattr(crawl_full, "main"))

    def test_extract_chapter_number_from_title(self):
        chapter = {
            "title": "Chapter 012",
            "url": "https://truyenqqko.com/truyen-tranh/comic/chuong-12.html?ref=latest",
        }
        self.assertEqual(crawl_full.extract_chapter_number(chapter), 12)

    def test_extract_chapter_number_from_url_suffix(self):
        chapter = {
            "title": "Read now",
            "url": "https://truyenqqko.com/truyen-tranh/comic/chuong-12.html?ref=latest",
        }
        self.assertEqual(crawl_full.extract_chapter_number(chapter), 12)

    def test_chapter_urls_by_number_uses_parsed_urls(self):
        chapters = [
            {
                "title": "Chapter 001",
                "url": "https://truyenqqko.com/truyen-tranh/comic/chuong-1.html",
            },
            {
                "title": "Chapter 002",
                "url": "https://truyenqqko.com/truyen-tranh/comic/chuong-2.html",
            },
        ]
        self.assertEqual(
            crawl_full.chapter_urls_by_number(chapters),
            {
                1: "https://truyenqqko.com/truyen-tranh/comic/chuong-1.html",
                2: "https://truyenqqko.com/truyen-tranh/comic/chuong-2.html",
            },
        )

    def test_chapter_urls_by_number_keeps_decimal_chapters(self):
        chapters = [{
            "title": "Chapter 012.5",
            "url": "https://example.com/comic/chuong-12.5.html",
        }]
        self.assertEqual(
            crawl_full.chapter_urls_by_number(chapters),
            {12.5: "https://example.com/comic/chuong-12.5.html"},
        )

    def test_enumerate_valid(self):
        mock_session = MagicMock()

        def mock_get(url, **kwargs):
            mock_resp = MagicMock()
            if url.endswith("/chuong-1") or url.endswith("/chuong-3"):
                mock_resp.url = url
            else:
                mock_resp.url = "https://nettruyen.gg/truyen/test" # redirected away
            return mock_resp

        mock_session.get.side_effect = mock_get

        valid = crawl_full.enumerate_valid(mock_session, "https://nettruyen.gg/truyen/test", 4)
        self.assertEqual(valid, [1, 3])


if __name__ == "__main__":
    unittest.main()
