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

    def test_process_grayscale_and_bilevel_modes(self):
        # Grayscale L mode
        img_gray = Image.new("L", (600, 900), color=128)
        buf_gray = io.BytesIO()
        img_gray.save(buf_gray, format="PNG")
        processed_gray = ImageProcessor.process_image(buf_gray.getvalue())
        self.assertEqual(processed_gray.format, "webp")

        # 1-bit monochrome 1 mode
        img_mono = Image.new("1", (600, 900), color=1)
        buf_mono = io.BytesIO()
        img_mono.save(buf_mono, format="PNG")
        processed_mono = ImageProcessor.process_image(buf_mono.getvalue())
        self.assertEqual(processed_mono.format, "webp")

    def test_process_palette_mode(self):
        img_p = Image.new("P", (500, 750))
        buf_p = io.BytesIO()
        img_p.save(buf_p, format="PNG")
        processed_p = ImageProcessor.process_image(buf_p.getvalue())
        self.assertEqual(processed_p.format, "webp")

    def test_process_cmyk_mode(self):
        img_cmyk = Image.new("CMYK", (400, 600), color=(100, 50, 0, 20))
        buf_cmyk = io.BytesIO()
        img_cmyk.save(buf_cmyk, format="JPEG")
        processed_cmyk = ImageProcessor.process_image(buf_cmyk.getvalue())
        self.assertEqual(processed_cmyk.format, "webp")

    def test_corrupt_bytes_rejection(self):
        with self.assertRaises(ValueError):
            ImageProcessor.process_image(b"not-an-image-corrupt-data-12345")

    def test_empty_buffer_rejection(self):
        with self.assertRaises(ValueError):
            ImageProcessor.process_image(b"")


if __name__ == "__main__":
    unittest.main()
