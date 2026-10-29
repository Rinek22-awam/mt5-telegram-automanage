"""Text messages from the signal channel -> UPDATE posts (keyword rules from config)."""
import re
from typing import Optional


def _has(text: str, words) -> bool:
    t = text.lower()
    return any(re.search(r"(?<![a-z])" + re.escape(w.lower()) + r"(?![a-z])", t) for w in words)


def is_highrisk(text: str, cfg: dict) -> bool:
    return _has(text or "", cfg["kata_highrisk"])


def classify(text: str, cfg: dict) -> str:
    """CANCEL / CLOSE / INFO. CLOSE wins over CANCEL when both appear."""
    if _has(text, cfg["kata_close"]):
        return "CLOSE"
    if _has(text, cfg["kata_cancel"]):
        return "CANCEL"
    return "INFO"


def build_update(text: str, cfg: dict, source: str) -> Optional[str]:
    text = (text or "").strip()
    if not text:
        return None
    action = classify(text, cfg)
    flat = " ".join(text.split())
    return f"UPDATE\nSumber: {source}\nAksi: {action}\nTeks: {flat[:800]}"
