import os
import zipfile
from typing import List
from PIL import Image

class ComicExporter:
    @staticmethod
    def export_to_cbz(image_paths: List[str], output_cbz_path: str) -> str:
        """
        Packs a list of image file paths into a single .cbz comic archive.
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_cbz_path)), exist_ok=True)
        with zipfile.ZipFile(output_cbz_path, 'w', zipfile.ZIP_DEFLATED) as cbz:
            for idx, img_path in enumerate(image_paths):
                if os.path.exists(img_path):
                    ext = os.path.splitext(img_path)[1]
                    arcname = f"{idx + 1:03d}{ext}"
                    cbz.write(img_path, arcname=arcname)
        return output_cbz_path

    @staticmethod
    def export_to_pdf(image_paths: List[str], output_pdf_path: str) -> str:
        """
        Compiles a list of image file paths into a single PDF document.
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_pdf_path)), exist_ok=True)
        valid_images = []

        for img_path in image_paths:
            if os.path.exists(img_path):
                try:
                    img = Image.open(img_path)
                    if img.mode in ("RGBA", "P", "LA"):
                        img = img.convert("RGB")
                    valid_images.append(img)
                except Exception as e:
                    print(f"[Warning] Skipped unreadable image for PDF ({img_path}): {e}")

        if not valid_images:
            raise ValueError("No valid images found to build PDF.")

        first_img = valid_images[0]
        rest_imgs = valid_images[1:] if len(valid_images) > 1 else []
        first_img.save(output_pdf_path, "PDF", resolution=100.0, save_all=True, append_images=rest_imgs)

        for img in valid_images:
            img.close()

        return output_pdf_path

    @staticmethod
    def convert_directory(input_dir: str, target_format: str = "cbz") -> List[str]:
        """
        Scans directory containing image subfolders and converts them to .cbz or .pdf.
        """
        if not os.path.exists(input_dir):
            raise ValueError(f"Input directory does not exist: {input_dir}")

        converted_files = []
        valid_exts = {".jpg", ".jpeg", ".png", ".webp"}

        # Case 1: Subdirectories represent chapters
        subdirs = [os.path.join(input_dir, d) for d in os.listdir(input_dir) if os.path.isdir(os.path.join(input_dir, d)) and not d.startswith("_")]

        if subdirs:
            for ch_dir in subdirs:
                ch_name = os.path.basename(ch_dir)
                images = sorted([
                    os.path.join(ch_dir, f) for f in os.listdir(ch_dir)
                    if os.path.splitext(f)[1].lower() in valid_exts
                ])
                if images:
                    if target_format == "cbz":
                        out_path = os.path.join(input_dir, f"{ch_name}.cbz")
                        ComicExporter.export_to_cbz(images, out_path)
                        converted_files.append(out_path)
                    elif target_format == "pdf":
                        out_path = os.path.join(input_dir, f"{ch_name}.pdf")
                        ComicExporter.export_to_pdf(images, out_path)
                        converted_files.append(out_path)
        else:
            # Case 2: Direct folder of images
            images = sorted([
                os.path.join(input_dir, f) for f in os.listdir(input_dir)
                if os.path.splitext(f)[1].lower() in valid_exts
            ])
            if images:
                ch_name = os.path.basename(os.path.normpath(input_dir))
                if target_format == "cbz":
                    out_path = os.path.join(os.path.dirname(input_dir), f"{ch_name}.cbz")
                    ComicExporter.export_to_cbz(images, out_path)
                    converted_files.append(out_path)
                elif target_format == "pdf":
                    out_path = os.path.join(os.path.dirname(input_dir), f"{ch_name}.pdf")
                    ComicExporter.export_to_pdf(images, out_path)
                    converted_files.append(out_path)

        return converted_files
