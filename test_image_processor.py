import io
import unittest
from PIL import Image
from comic_crawler.image_processor import ImageProcessor, ProcessedImage


class TestImageProcessor(unittest.TestCase):
    def test_process_png_to_webp(self):
        # Create a simple 800x1200 RGB PNG in memory
        img = Image.new("RGB", (800, 1200), color=(120, 50, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw_bytes = buf.getvalue()

        processed = ImageProcessor.process_image(raw_bytes)
        self.assertIsInstance(processed, ProcessedImage)
        self.assertEqual(processed.format, "webp")
        self.assertEqual(processed.width, 800)
        self.assertEqual(processed.height, 1200)
        self.assertTrue(len(processed.buffer) < len(raw_bytes))
        self.assertEqual(len(processed.original_hash), 64)

    def test_process_large_dimension_downscaling(self):
        # Create an oversized 2800x4000 image
        img = Image.new("RGB", (2800, 4000), color=(20, 150, 80))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        raw_bytes = buf.getvalue()

        processed = ImageProcessor.process_image(raw_bytes, max_width=1400)
        self.assertEqual(processed.width, 1400)
        self.assertEqual(processed.height, 2000)
        self.assertEqual(processed.format, "webp")

    def test_process_alpha_flattening(self):
        # Create an RGBA image with transparent background
        img = Image.new("RGBA", (400, 600), color=(255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw_bytes = buf.getvalue()

        processed = ImageProcessor.process_image(raw_bytes)
        self.assertEqual(processed.format, "webp")
        # Verify result is decoded as RGB without transparency error
        decoded = Image.open(io.BytesIO(processed.buffer))
        self.assertEqual(decoded.mode, "RGB")

    def test_process_oversized_height_guard(self):
        # Test WebP 16,383px height limit safeguard
        # Create a mock 100 x 17,000 px image
        img = Image.new("RGB", (100, 17000), color=(50, 50, 50))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        raw_bytes = buf.getvalue()

        processed = ImageProcessor.process_image(raw_bytes)
        self.assertEqual(processed.format, "jpeg")
        self.assertEqual(processed.height, 17000)

    def test_corrupt_bytes_rejection(self):
        with self.assertRaises(ValueError):
            ImageProcessor.process_image(b"not-an-image-corrupt-data-12345")

    def test_empty_buffer_rejection(self):
        with self.assertRaises(ValueError):
            ImageProcessor.process_image(b"")


if __name__ == "__main__":
    unittest.main()
