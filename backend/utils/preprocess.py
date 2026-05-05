import re
from typing import List


URL_PATTERN = re.compile(r"https?://\S+|www\.\S+")


def clean_text(text: str) -> str:
    """Basic text normalization for social posts."""
    text = text or ""
    text = text.strip().lower()
    text = URL_PATTERN.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def preprocess_posts(posts: List[str]) -> List[str]:
    """Remove duplicates and clean."""
    if not posts:
        return []
    seen = set()
    cleaned: List[str] = []
    for p in posts:
        if p is None:
            continue
        text = clean_text(str(p))
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned

