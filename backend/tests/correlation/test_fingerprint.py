"""Stage-0 primitives: fingerprint + group key derivation (pure functions)."""

from app.services.correlation.fingerprint import compute_fingerprint, compute_group_key

LABELS = {"host": "web-01", "service": "checkout", "env": "prod"}


def test_fingerprint_is_stable_and_order_independent():
    a = compute_fingerprint(
        "alertmanager", "HighCPU", {"host": "web-01", "env": "prod"}
    )
    b = compute_fingerprint(
        "alertmanager", "HighCPU", {"env": "prod", "host": "web-01"}
    )
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_fingerprint_differs_by_source_name_labels():
    base = compute_fingerprint("alertmanager", "HighCPU", LABELS)
    assert compute_fingerprint("datadog", "HighCPU", LABELS) != base
    assert compute_fingerprint("alertmanager", "HighMem", LABELS) != base
    assert (
        compute_fingerprint("alertmanager", "HighCPU", {**LABELS, "host": "web-02"})
        != base
    )


def test_group_key_priority_first():
    attrs = ["host", "service", "cluster"]
    # host present -> host wins even if service also present
    assert compute_group_key(LABELS, attrs) == "host=web-01"
    # no host -> falls through to service
    assert compute_group_key({"service": "checkout"}, attrs) == "service=checkout"
    # only cluster
    assert compute_group_key({"cluster": "c1"}, attrs) == "cluster=c1"


def test_group_key_none_when_no_attrs_match():
    assert compute_group_key({"env": "prod"}, ["host", "service", "cluster"]) is None
    assert compute_group_key({}, ["host"]) is None
