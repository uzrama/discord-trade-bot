from datetime import UTC, datetime


def utc_now_iso() -> str:
    """Get current UTC time in ISO format.

    Returns:
        ISO formatted UTC timestamp string.

    Examples:
        >>> utc_now_iso()
        '2026-03-24T16:44:44.151000+00:00'
    """
    return datetime.now(UTC).isoformat()
