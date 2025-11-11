from datetime import datetime, timezone

def now_iso() -> str:
    """Thời gian hiện tại dạng ISO-8601 UTC, đuôi 'Z'."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
