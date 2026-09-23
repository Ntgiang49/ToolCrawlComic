import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

import main
from comic_crawler.library import LibraryManager


class TestMainCrawlerManifest(unittest.TestCase):
    def test_meta_manifest_prevents_redownload_after_local_prune(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            library = LibraryManager(os.path.join(tmpdir, "library.json"))
            info = {
                "title": "Manifest Comic",
                "author": "Author",
                "category": "Action",
                "description": "Description",
                "chapters": [{
                    "title": "Chapter 001",
                    "url": "https://example.com/comic/chapter-1",
                }],
                "site_config": {},
            }
            first_crawler = MagicMock(num_threads=4)
            first_crawler.parse_comic_info.return_value = info
            first_crawler.download_chapter.side_effect = lambda title, url, config, output, fmt: (
                (os.makedirs(os.path.join(output, title), exist_ok=True), True)[1],
                os.path.join(output, title),
            )

            main.sync_single_comic(
                first_crawler, library, "https://example.com/comic", "images", tmpdir
            )

            meta_path = os.path.join(tmpdir, "Manifest Comic", "meta.json")
            with open(meta_path, encoding="utf-8") as meta_file:
                meta = json.load(meta_file)
            self.assertIn("1", meta["chapters"])

            second_crawler = MagicMock(num_threads=4)
            second_crawler.parse_comic_info.return_value = info
            main.sync_single_comic(
                second_crawler, library, "https://example.com/comic", "images", tmpdir
            )

            second_crawler.download_chapter.assert_not_called()

    def test_pending_manifest_entry_redownloads_when_local_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            library = LibraryManager(os.path.join(tmpdir, "library.json"))
            info = {
                "title": "Pending Comic",
                "chapters": [{
                    "title": "Chapter 001",
                    "url": "https://example.com/comic/chapter-1",
                }],
                "site_config": {},
            }
            comic_dir = os.path.join(tmpdir, "Pending Comic")
            os.makedirs(comic_dir)
            with open(os.path.join(comic_dir, "meta.json"), "w", encoding="utf-8") as meta_file:
                json.dump({"chapters": {"1": {
                    "number": 1, "title": "Chapter 001", "local_name": "Chapter 001",
                    "format": "images", "synced": False,
                }}}, meta_file)

            crawler = MagicMock(num_threads=4)
            crawler.parse_comic_info.return_value = info
            crawler.download_chapter.return_value = (True, "downloaded")

            main.sync_single_comic(crawler, library, "https://example.com/comic", "images", tmpdir)

            crawler.download_chapter.assert_called_once()


if __name__ == "__main__":
    unittest.main()
