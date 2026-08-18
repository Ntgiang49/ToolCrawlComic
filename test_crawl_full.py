import unittest
from unittest.mock import patch, MagicMock
import requests

import crawl_full

class TestCrawlFull(unittest.TestCase):
    def test_imports_and_constants(self):
        self.assertTrue(hasattr(crawl_full, "ThreadPoolExecutor"))
        self.assertTrue(hasattr(crawl_full, "enumerate_valid"))
        self.assertTrue(hasattr(crawl_full, "main"))

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
