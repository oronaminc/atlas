import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Any


def encode_cursor(created_at: datetime, item_id: uuid.UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "id": str(item_id)})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID] | None:
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(raw["t"]), uuid.UUID(raw["id"])
    except (ValueError, KeyError, binascii.Error, json.JSONDecodeError):
        return None


def page_meta(items: list[Any], limit: int) -> tuple[list[Any], dict[str, Any]]:
    """Items must be fetched with limit+1; trims the sentinel row and builds meta.

    Each item must expose .created_at and .id.
    """
    has_more = len(items) > limit
    items = items[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(last.created_at, last.id)
    return items, {"next_cursor": next_cursor, "has_more": has_more}
