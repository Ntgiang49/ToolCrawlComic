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
        target_dir = os.path.dirname(os.path.abspath(self.file_path))
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
        tmp_path = self.file_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.file_path)

    def add_or_update_comic(
        self,
        url: str,
        title: str,
        export_format: str = "cbz",
        threads: int = 8,
        total_chapters: int = 0,
        **kwargs
    ):
        if "comics" not in self.data:
            self.data["comics"] = {}

        fmt = kwargs.get("format", export_format)
        existing = self.data["comics"].get(url, {})
        self.data["comics"][url] = {
            "url": url,
            "title": title,
            "format": fmt or existing.get("format", "cbz"),
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
