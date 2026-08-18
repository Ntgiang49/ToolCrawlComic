import json
import os
from typing import Dict, Any, Optional
from .utils import extract_domain

class ConfigLoader:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Warning] Failed to read {self.config_path}: {e}")
        
        # Fallback default configuration
        return {
            "default_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
            },
            "sites": []
        }

    def get_site_config(self, url: str) -> Dict[str, Any]:
        domain = extract_domain(url)
        default_headers = self.config.get("default_headers", {})

        # Search for exact or partial domain match in config
        for site in self.config.get("sites", []):
            site_domain = site.get("domain", "").lower()
            if site_domain and (site_domain in domain or domain in site_domain):
                # Merge default headers with site specific headers
                merged_headers = default_headers.copy()
                merged_headers.update(site.get("headers", {}))
                
                # Auto set Referer if not specified
                if "Referer" not in merged_headers:
                    merged_headers["Referer"] = f"https://{domain}/"

                return {
                    "name": site.get("name", domain),
                    "domain": domain,
                    "headers": merged_headers,
                    "selectors": site.get("selectors", self._get_fallback_selectors()),
                    "chapter_order": site.get("chapter_order", "desc")
                }

        # Fallback config for unlisted sites
        merged_headers = default_headers.copy()
        merged_headers["Referer"] = f"https://{domain}/"
        return {
            "name": domain,
            "domain": domain,
            "headers": merged_headers,
            "selectors": self._get_fallback_selectors(),
            "chapter_order": "desc"
        }

    def _get_fallback_selectors(self) -> Dict[str, Any]:
        return {
            "comic_title": "h1.entry-title, h1.title, h1, .manga-title",
            "author": ".author, .author-name, span:contains('Author') + span",
            "category": ".genres a, .genre a, a[href*='genre'], a[href*='the-loai']",
            "description": ".description, .summary, .story-description, #noidungm",
            "chapter_list": "a[href*='chapter'], a[href*='ch-'], .chapter-list a, ul.clist a",
            "chapter_title": "text",
            "chapter_title_blacklist": ["Xem thêm", "Đọc mới nhất", "Đọc từ đầu", "Read First", "Read Last", "Read Now"],
            "page_images": "div.reading-content img, div.page-break img, div.chapter-video img, #chapter-images img, article img, .manga-read img",
            "image_url_attributes": ["src", "data-src", "data-lazy-src", "data-original", "data-cdn"]
        }
