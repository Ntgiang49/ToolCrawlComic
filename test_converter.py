import unittest
import os
import tempfile
from PIL import Image

from comic_crawler.exporter import ComicExporter

class TestConverter(unittest.TestCase):
    def test_convert_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a chapter subfolder with dummy image
            ch_dir = os.path.join(tmpdir, "Chapter 001")
            os.makedirs(ch_dir)
            
            img_path = os.path.join(ch_dir, "001.jpg")
            img = Image.new("RGB", (50, 50), color="blue")
            img.save(img_path)

            # Test convert to CBZ
            res = ComicExporter.convert_directory(tmpdir, target_format="cbz")
            self.assertEqual(len(res), 1)
            self.assertTrue(res[0].endswith("Chapter 001.cbz"))
            self.assertTrue(os.path.exists(res[0]))

if __name__ == "__main__":
    unittest.main()
