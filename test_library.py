import unittest
import os
import tempfile
from comic_crawler.library import LibraryManager

class TestLibraryManager(unittest.TestCase):
    def test_library_crud(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lib_file = os.path.join(tmpdir, "library.json")
            lib = LibraryManager(lib_file)
            
            # 1. Add comic
            lib.add_or_update_comic("https://example.com/solo", "Solo Leveling", format="cbz", threads=8)
            all_comics = lib.get_all_comics()
            self.assertIn("https://example.com/solo", all_comics)
            self.assertEqual(all_comics["https://example.com/solo"]["title"], "Solo Leveling")

            # 2. Reload library from disk
            lib2 = LibraryManager(lib_file)
            self.assertIn("https://example.com/solo", lib2.get_all_comics())

            # 3. Remove comic
            res = lib.remove_comic("https://example.com/solo")
            self.assertTrue(res)
            self.assertNotIn("https://example.com/solo", lib.get_all_comics())

if __name__ == "__main__":
    unittest.main()
