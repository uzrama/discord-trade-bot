import hashlib
import re


def sha1_text(text: str) -> str:
    """Generate SHA1 hash of text.

    Args:
        text: Text to hash.

    Returns:
        Hexadecimal SHA1 hash string.
    """
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def normalize_symbol(raw: str, suffix: str = "USDT") -> str:
    """Normalize trading symbol by removing special characters and adding suffix.

    Args:
        raw: Raw symbol string (e.g., "BTC", "btc/usdt", "BTC-USDT").
        suffix: Suffix to add if not present (default: "USDT").

    Returns:
        Normalized symbol (e.g., "BTCUSDT").

    Examples:
        >>> normalize_symbol("BTC")
        'BTCUSDT'
        >>> normalize_symbol("btc/usdt")
        'BTCUSDT'
        >>> normalize_symbol("BTCUSDT")
        'BTCUSDT'
    """
    s = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
    if not s:
        return s
    if s.endswith(suffix):
        return s
    return f"{s}{suffix}"
