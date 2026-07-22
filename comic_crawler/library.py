import json
import os
from datetime import datetime
from typing import Dict, Any

class LibraryManager:
    """
    Manages library.json tracking subscribed comics, format preferences, and last synced timestamps.
    """
    def __init__(self, file_path: str = "library.json"):
        self.file_path = file_path
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    if isinstance(content, dict) and "comics" in content:
                        return content
            except Exception as e:
                print(f"[Warning] Failed to load {self.file_path}: {e}")
        return {"comics": {}}

    def save(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.file_path)), exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def add_or_update_comic(self, url: str, title: str, format: str = "cbz", threads: int = 8, total_chapters: int = 0):
        if "comics" not in self.data:
            self.data["comics"] = {}

        existing = self.data["comics"].get(url, {})
        self.data["comics"][url] = {
            "url": url,
            "title": title,
            "format": format or existing.get("format", "cbz"),
            "threads": threads or existing.get("threads", 8),
            "total_chapters": max(total_chapters, existing.get("total_chapters", 0)),
            "last_synced": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.save()

    def get_all_comics(self) -> Dict[str, Any]:
        return self.data.get("comics", {})

    def remove_comic(self, url: str) -> bool:
        if "comics" in self.data and url in self.data["comics"]:
            del self.data["comics"][url]
            self.save()
            return True
        return False
