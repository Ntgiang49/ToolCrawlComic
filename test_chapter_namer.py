import unittest
from comic_crawler.chapter_namer import ChapterNamer

class TestChapterNamer(unittest.TestCase):
    def test_extract_chapter_number(self):
        self.assertEqual(ChapterNamer.extract_number("Read Chapter 12.5 online"), 12.5)
        self.assertEqual(ChapterNamer.extract_number("Chapter 001 - The Beginning"), 1.0)
        self.assertEqual(ChapterNamer.extract_number("Ch. 42"), 42.0)
        self.assertIsNone(ChapterNamer.extract_number("Extra Bonus Story"))

    def test_format_padded_name(self):
        self.assertEqual(ChapterNamer.format_chapter_name("Chapter 1", total_chapters=150), "Chapter 001")
        self.assertEqual(ChapterNamer.format_chapter_name("Chapter 12.5", total_chapters=150), "Chapter 012.5")
        self.assertEqual(ChapterNamer.format_chapter_name("Chapter 5", total_chapters=20), "Chapter 005")

if __name__ == "__main__":
    unittest.main()
