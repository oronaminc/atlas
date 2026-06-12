"""PromQL/LogQL validation.

Local checks catch structural mistakes (unbalanced brackets/quotes, empty
expressions). When the metrics/logs backend is reachable, the expression is
also parsed remotely via an instant query for authoritative validation.
"""

import logging

from app.models.rule import Datasource

logger = logging.getLogger(__name__)

_PAIRS = {")": "(", "]": "[", "}": "{"}


def local_syntax_errors(expr: str) -> list[str]:
    errors: list[str] = []
    expr = expr.strip()
    if not expr:
        return ["expression is empty"]

    stack: list[str] = []
    in_string: str | None = None
    escaped = False
    for ch in expr:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in ("'", '"', "`"):
            in_string = ch
        elif ch in "([{":
            stack.append(ch)
        elif ch in ")]}":
            if not stack or stack[-1] != _PAIRS[ch]:
                errors.append(f"unbalanced '{ch}'")
                break
            stack.pop()
    if in_string:
        errors.append("unterminated string literal")
    if stack and not errors:
        errors.append(f"unclosed '{stack[-1]}'")
    return errors


async def validate_expr(expr: str, datasource: Datasource) -> list[str]:
    """Returns a list of validation errors (empty list = valid)."""
    errors = local_syntax_errors(expr)
    if errors:
        return errors

    # Best-effort remote parse: a failing query with a parse error message is
    # authoritative; transport errors fall back to local-only validation.
    try:
        if datasource == Datasource.metrics:
            from app.integrations.mimir_ruler import MimirQueryClient

            client = MimirQueryClient()
        else:
            from app.integrations.loki import LokiClient

            client = LokiClient()
        try:
            response = await client.request(
                "GET",
                ("/api/v1/query" if datasource == Datasource.metrics else "/loki/api/v1/query"),
                params={"query": expr},
                retries=1,
            )
            if response.status_code == 400:
                detail = response.json().get("error", "parse error")
                return [detail]
        finally:
            await client.aclose()
    except Exception:
        logger.debug("remote validation unavailable; local checks only")
    return []
