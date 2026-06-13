"""Feature A: redaction, prompt-hash cache, per-service config isolation,
tenancy (A's incident never hits B's endpoint), failure/timeout/retry, quota,
crash-resume via lease. No real network — a FakeLLM/transport is injected."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.integrations.llm import LLMClient, LLMError, LLMTimeout
from app.models.alerting import AlertEvent, Incident, IncidentEvent, IncidentStatus
from app.models.llm import IncidentAnalysis, LLMConfig
from app.services.llm_analysis import (
    ANALYSIS_LEASE_SECONDS,
    build_prompt,
    claim_pending_analyses,
    get_llm_config,
    is_external,
    redact_labels,
    run_analysis,
)

NOW = datetime(2026, 6, 13, 12, 0, 0, tzinfo=UTC)


def _resp(content: str, tokens: int = 42):
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}], "usage": {"total_tokens": tokens}},
    )


class FakeLLM:
    """Records calls; returns a canned completion or raises."""

    def __init__(self, content="ROOT CAUSE: disk full\nSUMMARY: db-01 disk filled up.", exc=None):
        self.calls: list[tuple[str, str]] = []
        self.content = content
        self.exc = exc

    async def complete(self, system, user, *, max_tokens=512):
        self.calls.append((system, user))
        if self.exc:
            raise self.exc
        return self.content, 42


async def _incident(db, tenant_id, *, title="DiskFull on db-01", labels=None):
    inc = Incident(
        tenant_id=tenant_id,
        title=title,
        status=IncidentStatus.open,
        severity="critical",
        group_key="host=db-01",
        first_seen=NOW,
        last_seen=NOW,
        alert_count=1,
    )
    db.add(inc)
    await db.flush()
    db.add(
        AlertEvent(
            tenant_id=tenant_id,
            fingerprint=f"fp{uuid.uuid4().hex[:8]}",
            source="alertmanager",
            name="DiskFull",
            severity="critical",
            status="firing",
            labels=labels or {"host": "db-01", "severity": "critical"},
            annotations={"summary": "disk at 99%"},
            starts_at=NOW,
            received_at=NOW,
            incident_id=inc.id,
        )
    )
    db.add(IncidentEvent(tenant_id=tenant_id, incident_id=inc.id, kind="created", payload={}))
    await db.flush()
    return inc


async def _cfg(db, tenant_id, **kw):
    defaults = dict(
        enabled=True, base_url="http://vllm.internal:8000", model="llama-3", daily_quota=200
    )
    defaults.update(kw)
    cfg = LLMConfig(tenant_id=tenant_id, **defaults)
    db.add(cfg)
    await db.flush()
    return cfg


# --- redaction ---


def test_redaction_strips_secrets_internal():
    labels = {"host": "db-01", "api_key": "abcd1234verysecretvalue", "token": "xyz"}
    out = redact_labels(labels, external=False)
    assert out["host"] == "db-01"
    assert out["api_key"] == "***redacted***"
    assert out["token"] == "***redacted***"


def test_redaction_external_drops_unknown_keys():
    labels = {"host": "db-01", "internal_note": "secret topology", "severity": "critical"}
    out = redact_labels(labels, external=True)
    assert set(out) == {"host", "severity"}  # unknown key dropped entirely
    out_internal = redact_labels(labels, external=False)
    assert "internal_note" in out_internal  # kept (only secret-shaped redacted)


def test_is_external_classification():
    assert is_external("https://api.openai.com") is True
    assert is_external("http://vllm.internal:8000") is False
    assert is_external("http://10.0.0.5:8000") is False
    assert is_external("http://localhost:11434") is False


async def test_secret_shaped_value_redacted_even_on_allowed_key(db, tenant_a):
    cfg = await _cfg(db, tenant_a.id, base_url="http://vllm.internal:8000")
    inc = await _incident(
        db, tenant_a.id, labels={"host": "Bearer abcdef0123456789abcdef0123456789"}
    )
    alerts = [(await db.execute(select(AlertEvent))).scalars().first()]
    _system, user, _h = build_prompt(inc, alerts, [], cfg)
    assert "Bearer abcdef" not in user
    assert "redacted" in user


# --- tenancy / config isolation ---


async def test_config_resolves_per_service_then_default(db, tenant_a, tenant_b):
    await _cfg(db, None, base_url="http://default.internal:8000", model="default-m")
    await _cfg(db, tenant_a.id, base_url="http://a.internal:8000", model="a-m")
    await db.commit()
    a = await get_llm_config(db, tenant_a.id)
    assert a.base_url == "http://a.internal:8000"
    b = await get_llm_config(db, tenant_b.id)  # no B row -> default
    assert b.base_url == "http://default.internal:8000"


async def test_analysis_sends_only_to_own_service_endpoint(db, tenant_a, tenant_b):
    # A and B both configured with DISTINCT endpoints; analysing A's incident
    # must build a client for A and never consult B's config.
    await _cfg(db, tenant_a.id, base_url="http://a.internal:8000", model="a-m")
    await _cfg(db, tenant_b.id, base_url="http://b.internal:8000", model="b-m")
    inc = await _incident(db, tenant_a.id)
    analysis = IncidentAnalysis(incident_id=inc.id, tenant_id=tenant_a.id, status="running")
    db.add(analysis)
    await db.flush()

    # run_analysis resolves config by analysis.tenant_id -> A's config only
    fake = FakeLLM()
    await run_analysis(db, analysis, client_factory=lambda: fake)
    await db.commit()
    assert analysis.status == "done"
    assert analysis.model == "a-m"  # A's model, never b-m
    assert fake.calls  # exactly one call made


# --- cache / idempotency ---


async def test_prompt_hash_cache_skips_llm_call(db, tenant_a):
    await _cfg(db, tenant_a.id)
    inc = await _incident(db, tenant_a.id)
    analysis = IncidentAnalysis(incident_id=inc.id, tenant_id=tenant_a.id, status="running")
    db.add(analysis)
    await db.flush()

    fake = FakeLLM()
    await run_analysis(db, analysis, client_factory=lambda: fake)
    assert analysis.status == "done"
    assert len(fake.calls) == 1
    first_hash = analysis.prompt_hash

    # re-run same prompt -> cached, no second call
    analysis.status = "running"
    fake2 = FakeLLM()
    await run_analysis(db, analysis, client_factory=lambda: fake2)
    assert analysis.status == "done"
    assert fake2.calls == []  # cache hit
    assert analysis.prompt_hash == first_hash


# --- failure / quota ---


async def test_failure_recorded_never_raises(db, tenant_a):
    await _cfg(db, tenant_a.id)
    inc = await _incident(db, tenant_a.id)
    analysis = IncidentAnalysis(incident_id=inc.id, tenant_id=tenant_a.id, status="running")
    db.add(analysis)
    await db.flush()
    fake = FakeLLM(exc=LLMTimeout("timeout"))
    await run_analysis(db, analysis, client_factory=lambda: fake)  # must not raise
    assert analysis.status == "failed"
    assert "timeout" in analysis.error
    assert analysis.attempts == 1


async def test_disabled_or_unconfigured_fails_cleanly(db, tenant_a):
    await _cfg(db, tenant_a.id, enabled=False)
    inc = await _incident(db, tenant_a.id)
    analysis = IncidentAnalysis(incident_id=inc.id, tenant_id=tenant_a.id, status="running")
    db.add(analysis)
    await db.flush()
    await run_analysis(db, analysis, client_factory=lambda: FakeLLM())
    assert analysis.status == "failed" and "not configured" in analysis.error


async def test_daily_quota_enforced(db, tenant_a):
    await _cfg(db, tenant_a.id, daily_quota=1)
    # one already-done analysis today consumes the quota
    inc0 = await _incident(db, tenant_a.id, title="prior")
    db.add(
        IncidentAnalysis(
            incident_id=inc0.id,
            tenant_id=tenant_a.id,
            status="done",
            completed_at=datetime.now(UTC),
            summary="x",
        )
    )
    inc = await _incident(db, tenant_a.id)
    analysis = IncidentAnalysis(incident_id=inc.id, tenant_id=tenant_a.id, status="running")
    db.add(analysis)
    await db.flush()
    await run_analysis(db, analysis, client_factory=lambda: FakeLLM())
    assert analysis.status == "failed" and "quota" in analysis.error


# --- claim / crash-resume ---


async def test_claim_is_exclusive_and_lease_resumes(db, tenant_a):
    await _cfg(db, tenant_a.id)
    inc = await _incident(db, tenant_a.id)
    db.add(IncidentAnalysis(incident_id=inc.id, tenant_id=tenant_a.id, status="pending"))
    await db.commit()

    claimed = await claim_pending_analyses(db, worker_id="w1", now=NOW)
    assert len(claimed) == 1 and claimed[0].status == "running"
    await db.commit()

    # within lease: not re-claimable
    again = await claim_pending_analyses(db, worker_id="w2", now=NOW + timedelta(seconds=30))
    assert again == []
    # after lease expiry: another worker resumes
    resumed = await claim_pending_analyses(
        db, worker_id="w2", now=NOW + timedelta(seconds=ANALYSIS_LEASE_SECONDS + 1)
    )
    assert len(resumed) == 1


# --- the OpenAI-compatible client itself (mock transport) ---


async def test_llm_client_parses_and_retries():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return _resp("ROOT CAUSE: x\nSUMMARY: y")

    client = LLMClient(
        "http://vllm.internal:8000", "key", "m", transport=httpx.MockTransport(handler)
    )
    content, tokens = await client.complete("sys", "usr")
    assert "ROOT CAUSE" in content and tokens == 42
    assert calls["n"] == 2  # retried the 503

    # auth header present
    seen = {}

    def h2(request):
        seen["auth"] = request.headers.get("authorization")
        return _resp("ok")

    c2 = LLMClient("http://x.internal", "secret-key", "m", transport=httpx.MockTransport(h2))
    await c2.complete("s", "u")
    assert seen["auth"] == "Bearer secret-key"


async def test_llm_client_4xx_no_retry():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    client = LLMClient("http://x.internal", None, "m", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError):
        await client.complete("s", "u")
    assert calls["n"] == 1  # 4xx not retried
