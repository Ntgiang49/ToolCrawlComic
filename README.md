# Comic Crawler Easy

A fast, lightweight, modular Python comic crawler with **1-Command Auto-Update**, **Library Tracking**, **Zero-Padded Chapter Naming**, **Format Conversion**, and multi-format exports (**CBZ**, **PDF**, **Images**).

---

## Key Features

- **1-Command Batch Auto-Update (`python main.py update`)**:
  - Automatically updates all your favorite tracked comics in **one single command** or 1 double-click ([run_update.bat](file:///d:/Tool_crawl_comic/run_update.bat))!
  - **Incremental Sync**: Inspects local files and skips existing chapters instantly without re-downloading old chapters.
- **Easy Single URL Download (`python main.py <URL>`)**:
  - Paste any comic URL to download all chapters and automatically add it to your library tracker (`library.json`).
- **Local Folder Converter (`python main.py convert <PATH>`)**:
  - Converts existing downloaded image folders into `.cbz` or `.pdf` comic files.
- **Zero-Padded Chapter Naming**:
  - Automatically numbers files consistently (e.g., `Chapter 001.cbz`, `Chapter 012.5.cbz`, `Chapter 150.cbz`) so comic readers sort chapters chronologically.
- **Multiple Export Formats**:
  - `.cbz` (Comic Book Zip for Tachiyomi, Kuro Reader, YACReader, CDisplay)
  - `.pdf` (Single compiled PDF document per chapter)
  - Raw Image Folders (`.jpg` / `.png` folders)

---

## Installation

```bash
pip install -r requirements.txt
```

---

## How to Use

### 1. Download & Track a Comic
```bash
python main.py "https://example-manga.com/series/solo-leveling"
```

### 2. Update All Favorite Comics (1-Command Sync)
```bash
python main.py update
```
*Or double click `run_update.bat` on Windows!*

### 3. List Tracked Comics & Remove
```bash
# View all tracked comics
python main.py list

# Remove a comic from tracking
python main.py remove "https://example-manga.com/series/solo-leveling"
```

### 4. Convert Local Image Folders to CBZ / PDF
```bash
python main.py convert "downloads/Solo Leveling" --format cbz
python main.py convert "downloads/Solo Leveling" --format pdf
```

### 5. Interactive Mode
Simply run without arguments or double-click `run_interactive.bat`:
```bash
python main.py
```
