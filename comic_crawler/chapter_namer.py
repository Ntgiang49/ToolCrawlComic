import re

class ChapterNamer:
    @staticmethod
    def extract_number(title: str) -> float | None:
        """
        Extracts chapter number (integer or float) from title string.
        Examples:
            "Read Chapter 12.5 online" -> 12.5
            "Chapter 001 - The Beginning" -> 1.0
            "Ch. 42" -> 42.0
        """
        if not title:
            return None
        match = re.search(r'(?:chapter|ch\.?|ch\s+)\s*(\d+(?:\.\d+)?)', title, re.IGNORECASE)
        if not match:
            match = re.search(r'\b(\d+(?:\.\d+)?)\b', title)
        
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    @staticmethod
    def format_chapter_name(raw_title: str, total_chapters: int = 100) -> str:
        """
        Formats title to zero-padded chapter name (e.g. Chapter 001, Chapter 012.5).
        """
        num = ChapterNamer.extract_number(raw_title)
        if num is None:
            return raw_title

        # Determine padding width based on total count (minimum 3 digits)
        padding_width = max(3, len(str(int(total_chapters))))
        
        is_float = (num % 1 != 0)
        if is_float:
            int_part = int(num)
            dec_part = str(num).split('.')[1]
            padded = f"{int_part:0{padding_width}d}.{dec_part}"
        else:
            padded = f"{int(num):0{padding_width}d}"

        return f"Chapter {padded}"
