import re
import urllib.parse

def sanitize_filename(name: str) -> str:
    """
    Sanitizes string to be safe for filenames on Windows, macOS, and Linux.
    """
    if not name:
        return "unnamed"
    # Strip illegal filename characters: \ / : * ? " < > |
    name = re.sub(r'[\\/:*?"<>|]', '', name)
    # Normalize whitespaces
    name = re.sub(r'\s+', ' ', name).strip()
    return name or "unnamed"

def make_absolute_url(base_url: str, link: str) -> str:
    """
    Converts relative URL to absolute URL given a base URL.
    """
    if not link:
        return ""
    link = link.strip()
    if link.startswith("//"):
        parsed_base = urllib.parse.urlparse(base_url)
        return f"{parsed_base.scheme}:{link}"
    return urllib.parse.urljoin(base_url, link)

def extract_domain(url: str) -> str:
    """
    Extracts base domain from URL.
    """
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc.lower()
