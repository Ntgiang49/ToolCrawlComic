"""
In-memory Image Processing Engine for Comic Scans.
Handles validation, dimension clamping, alpha flattening, SHA-256 hashing,
and WebP transcoding with dimension safeguards.
"""

import hashlib
import io
from dataclasses import dataclass
from PIL import Image

MAX_WEBP_DIMENSION = 16383
TARGET_MAX_WIDTH = 1400


@dataclass
class ProcessedImage:
    buffer: bytes
    format: str  # "webp" or "jpeg"
    width: int
    height: int
    original_hash: str
    byte_size: int


class ImageProcessor:
    @staticmethod
    def process_image(
        raw_bytes: bytes,
        max_width: int = TARGET_MAX_WIDTH,
        quality: int = 81,
        method: int = 4,
    ) -> ProcessedImage:
        """
        Process and transcode an image buffer into an optimized WebP (or JPEG fallback).
        """
        if not raw_bytes:
            raise ValueError("Cannot process empty image buffer.")

        # 1. Compute SHA-256 hash of raw input
        original_hash = hashlib.sha256(raw_bytes).hexdigest()

        # 2. Open and validate image header
        try:
            img = Image.open(io.BytesIO(raw_bytes))
            img.load()  # Force load pixel data to detect truncated/corrupt images
        except Exception as e:
            raise ValueError(f"Corrupted or unsupported image file: {e}") from e

        orig_w, orig_h = img.size
        if orig_w <= 0 or orig_h <= 0:
            raise ValueError(f"Invalid image dimensions: {orig_w}x{orig_h}")

        # 3. Downscale width if excessive, preserving aspect ratio
        if orig_w > max_width:
            new_w = max_width
            new_h = max(1, int(orig_h * (max_width / orig_w)))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        curr_w, curr_h = img.size

        # 4. Alpha Channel Optimization (flatten opaque/transparent backgrounds for comics)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            # Create a solid white background and paste RGBA image
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[3])  # Split alpha as mask
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # 5. Dimension Guard: WebP hard specification limit is 16,383 x 16,383 px
        out_buf = io.BytesIO()
        is_oversized_for_webp = curr_w > MAX_WEBP_DIMENSION or curr_h > MAX_WEBP_DIMENSION

        if is_oversized_for_webp:
            # Fallback to Progressive JPEG for extreme webtoon vertical strips
            img.save(out_buf, format="JPEG", quality=82, progressive=True, optimize=True)
            final_format = "jpeg"
        else:
            # Standard WebP Transcoding
            img.save(
                out_buf,
                format="WEBP",
                quality=quality,
                method=method,
            )
            final_format = "webp"

        optimized_bytes = out_buf.getvalue()

        return ProcessedImage(
            buffer=optimized_bytes,
            format=final_format,
            width=curr_w,
            height=curr_h,
            original_hash=original_hash,
            byte_size=len(optimized_bytes),
        )
