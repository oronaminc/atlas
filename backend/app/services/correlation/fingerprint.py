"""Pure derivation functions: dedup fingerprint and grouping key."""

import hashlib


def compute_fingerprint(source: str, name: str, labels: dict[str, str]) -> str:
    """Identity of a unique alert stream: source + name + sorted labels."""
    parts = [source, name] + [f"{k}={v}" for k, v in sorted(labels.items())]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def compute_group_key(labels: dict[str, str], group_attrs: list[str]) -> str | None:
    """Priority-first: the first configured attr present in labels wins,
    value-qualified (e.g. 'host=web-01'). None = never cross-grouped."""
    for attr in group_attrs:
        value = labels.get(attr)
        if value:
            return f"{attr}={value}"
    return None
