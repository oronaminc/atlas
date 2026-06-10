from typing import Any


def envelope(
    data: Any = None,
    error: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Standard response envelope: {data, error, meta}."""
    return {"data": data, "error": error, "meta": meta}


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        err["details"] = details
    return envelope(data=None, error=err)
