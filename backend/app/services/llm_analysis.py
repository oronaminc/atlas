"""Incident-analysis service: config resolution, redaction, prompt building,
prompt-hash caching, and the worker-side run. Tenancy: the analysis row
carries the incident's stamped tenant_id; config is resolved by THAT id, so
a service's incident is only ever sent to its own configured endpoint.
"""

import hashlib
import ipaddress
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_secret
from app.integrations.llm import LLMClient
from app.models.alerting import AlertEvent, Incident, IncidentEvent
from app.models.llm import IncidentAnalysis, LLMConfig

logger = logging.getLogger(__name__)

# label/annotation keys whose VALUES must never leave the box
_SECRET_KEY_RE = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|credential|private)", re.I
)
# obvious secret-shaped values
_SECRET_VAL_RE = re.compile(
    r"(eyJ[A-Za-z0-9_-]{10,}\.|Bearer\s+\S+|[A-Za-z0-9+/]{40,}={0,2}|[0-9a-f]{40,})"
)
_REDACTED = "***redacted***"
# label keys safe to send to an EXTERNAL endpoint (strict allowlist)
_EXTERNAL_LABEL_ALLOWLIST = {
    "alertname",
    "severity",
    "host",
    "service",
    "cluster",
    "job",
    "instance",
}


async def get_llm_config(db: AsyncSession, tenant_id: uuid.UUID | None) -> LLMConfig | None:
    """The service's own row, else the platform-default (NULL) row. Returns
    None if neither exists or the resolved row is disabled."""
    row = (
        await db.execute(select(LLMConfig).where(LLMConfig.tenant_id == tenant_id).limit(1))
    ).scalar_one_or_none()
    if row is None and tenant_id is not None:
        row = (
            await db.execute(select(LLMConfig).where(LLMConfig.tenant_id.is_(None)).limit(1))
        ).scalar_one_or_none()
    if row is None or not row.enabled or not row.base_url or not row.model:
        return None
    return row


def is_external(base_url: str) -> bool:
    """External = not a private/loopback host. Drives stricter redaction."""
    host = (urlparse(base_url).hostname or "").lower()
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".svc"):
        return False
    try:
        return not ipaddress.ip_address(host).is_private
    except ValueError:
        # a hostname (not an IP): treat dotted public-looking names as external
        return "." in host and not host.endswith(".internal")


def _redact_value(key: str, value: str) -> str:
    if _SECRET_KEY_RE.search(key) or _SECRET_VAL_RE.search(str(value)):
        return _REDACTED
    return value


def redact_labels(labels: dict, *, external: bool) -> dict:
    out = {}
    for k, v in (labels or {}).items():
        if external and k not in _EXTERNAL_LABEL_ALLOWLIST:
            continue  # strict: drop unknown keys entirely for external endpoints
        out[k] = _redact_value(k, str(v))
    return out


def redact_annotations(ann: dict, *, external: bool, cap: int) -> dict:
    out = {}
    for k, v in (ann or {}).items():
        val = _redact_value(k, str(v))
        if external:
            val = val[:cap]
        out[k] = val
    return out


def build_prompt(
    incident: Incident, alerts: list[AlertEvent], timeline: list[IncidentEvent], cfg: LLMConfig
) -> tuple[str, str, str]:
    """Returns (system, user, prompt_hash). Redaction applied per endpoint."""
    external = is_external(cfg.base_url)
    cap = 300 if external else 2000
    lines = [
        f"Incident: {incident.title}",
        f"Severity: {incident.severity}  Host/group: {incident.group_key or '-'}",
        f"Window: {incident.first_seen.isoformat()} -> {incident.last_seen.isoformat()}",
        f"Alert count: {incident.alert_count}",
        "",
        "Alerts:",
    ]
    for a in alerts:
        labels = redact_labels(a.labels, external=external)
        ann = redact_annotations(a.annotations, external=external, cap=cap)
        lines.append(
            f"- {a.name} [{a.severity}] x{a.dedup_count} @ {a.received_at.isoformat()} "
            f"labels={labels} annotations={ann}"
        )
    lines.append("")
    lines.append("Timeline: " + ", ".join(e.kind for e in timeline))
    user = "\n".join(lines)[: cfg.max_prompt_chars]
    system = (
        "You are an SRE assistant. Given an incident's grouped alerts and "
        "timeline, produce a concise root-cause hypothesis and a short summary. "
        "Respond as: ROOT CAUSE: <one line>\\nSUMMARY: <2-4 sentences>."
    )
    prompt_hash = hashlib.sha256(f"{cfg.model}\x1f{user}".encode()).hexdigest()
    return system, user, prompt_hash


def parse_completion(text: str) -> tuple[str, str]:
    """Split the model output into (root_cause, summary); tolerant of format."""
    root, summary = "", text.strip()
    m = re.search(r"ROOT CAUSE:\s*(.+?)(?:\n|$)", text, re.I)
    if m:
        root = m.group(1).strip()
    m2 = re.search(r"SUMMARY:\s*(.+)", text, re.I | re.S)
    if m2:
        summary = m2.group(1).strip()
    return root, summary


async def _quota_used_today(db: AsyncSession, tenant_id: uuid.UUID | None) -> int:
    since = datetime.now(UTC) - timedelta(days=1)
    return (
        await db.execute(
            select(func.count())
            .select_from(IncidentAnalysis)
            .where(
                IncidentAnalysis.tenant_id == tenant_id,
                IncidentAnalysis.status == "done",
                IncidentAnalysis.completed_at > since,
            )
        )
    ).scalar_one()


async def run_analysis(
    db: AsyncSession, analysis: IncidentAnalysis, *, client_factory=None
) -> None:
    """Execute one analysis job (already claimed). Resolves config by the
    job's tenant_id, builds+caches by prompt_hash, calls the LLM, stores the
    result. Never raises — failures are recorded on the row."""
    incident = await db.get(Incident, analysis.incident_id)
    if incident is None:
        analysis.status = "failed"
        analysis.error = "incident gone"
        await db.flush()
        return

    cfg = await get_llm_config(db, analysis.tenant_id)
    if cfg is None:
        analysis.status = "failed"
        analysis.error = "LLM not configured for this service"
        await db.flush()
        return

    # quota
    if cfg.daily_quota > 0 and await _quota_used_today(db, analysis.tenant_id) >= cfg.daily_quota:
        analysis.status = "failed"
        analysis.error = f"daily LLM quota {cfg.daily_quota} reached"
        await db.flush()
        return

    alerts = list(
        (
            await db.execute(
                select(AlertEvent)
                .where(AlertEvent.incident_id == incident.id)
                .order_by(AlertEvent.received_at.asc())
            )
        ).scalars()
    )
    timeline = list(
        (
            await db.execute(
                select(IncidentEvent)
                .where(IncidentEvent.incident_id == incident.id)
                .order_by(IncidentEvent.created_at.asc())
            )
        ).scalars()
    )
    system, user, prompt_hash = build_prompt(incident, alerts, timeline, cfg)

    # cache: same prompt already analysed -> reuse, no LLM call
    if analysis.prompt_hash == prompt_hash and analysis.summary:
        analysis.status = "done"
        await db.flush()
        return

    api_key = decrypt_secret(cfg.api_key) if cfg.api_key else None
    factory = client_factory or (
        lambda: LLMClient(
            cfg.base_url, api_key, cfg.model, timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS
        )
    )
    client = factory()
    try:
        content, tokens = await client.complete(system, user, max_tokens=cfg.max_completion_tokens)
    except Exception as exc:  # noqa: BLE001 — record, never propagate
        analysis.attempts += 1
        analysis.status = "failed"
        analysis.error = str(exc)[:2000]
        await db.flush()
        return

    root, summary = parse_completion(content)
    analysis.root_cause = root
    analysis.summary = summary
    analysis.model = cfg.model
    analysis.tokens_used = tokens
    analysis.prompt_hash = prompt_hash
    analysis.status = "done"
    analysis.error = None
    analysis.completed_at = datetime.now(UTC)
    await db.flush()


ANALYSIS_LEASE_SECONDS = 120
ANALYSIS_MAX_ATTEMPTS = 3


async def claim_pending_analyses(
    db: AsyncSession, *, worker_id: str, now: datetime, limit: int = 5
) -> list[IncidentAnalysis]:
    """CAS+lease claim of pending/failed analysis jobs (crash-safe like the
    notification outbox). Failed jobs under the attempt cap are retried."""
    from sqlalchemy import or_, update

    lease_cutoff = now - timedelta(seconds=ANALYSIS_LEASE_SECONDS)
    guard = (
        # include "running" so a crashed job (claimed, never finished) resumes
        # once its lease expires; lease_cutoff below protects in-flight ones
        IncidentAnalysis.status.in_(("pending", "failed", "running")),
        IncidentAnalysis.attempts < ANALYSIS_MAX_ATTEMPTS,
        or_(
            IncidentAnalysis.claimed_at.is_(None),
            IncidentAnalysis.claimed_at < lease_cutoff,
        ),
    )
    candidates = select(IncidentAnalysis.id).where(*guard).limit(limit)
    if db.bind.dialect.name == "postgresql":
        candidates = candidates.with_for_update(skip_locked=True)
    ids = list((await db.execute(candidates)).scalars())
    claimed = []
    for jid in ids:
        res = await db.execute(
            update(IncidentAnalysis)
            .where(IncidentAnalysis.id == jid, *guard)
            .values(claimed_at=now, claimed_by=worker_id, status="running")
            .execution_options(synchronize_session=False)
        )
        if res.rowcount == 1:
            claimed.append(jid)
    if not claimed:
        return []
    rows = await db.execute(
        select(IncidentAnalysis)
        .where(IncidentAnalysis.id.in_(claimed))
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


async def enqueue_auto_analyses(db: AsyncSession, *, now: datetime, lookback_hours: int = 1) -> int:
    """For services with auto_analyze enabled, create a pending analysis for
    recent incidents that have none yet. Bounded (recent window, opt-in only)
    so it never touches the correlation hot path. Returns rows created."""
    cfgs = list(
        (
            await db.execute(
                select(LLMConfig).where(
                    LLMConfig.auto_analyze.is_(True), LLMConfig.enabled.is_(True)
                )
            )
        ).scalars()
    )
    if not cfgs:
        return 0
    since = now - timedelta(hours=lookback_hours)
    created = 0
    for cfg in cfgs:
        incident_ids = list(
            (
                await db.execute(
                    select(Incident.id).where(
                        Incident.tenant_id == cfg.tenant_id,
                        Incident.created_at >= since,
                    )
                )
            ).scalars()
        )
        if not incident_ids:
            continue
        have = set(
            (
                await db.execute(
                    select(IncidentAnalysis.incident_id).where(
                        IncidentAnalysis.incident_id.in_(incident_ids)
                    )
                )
            ).scalars()
        )
        for iid in incident_ids:
            if iid not in have:
                db.add(IncidentAnalysis(incident_id=iid, tenant_id=cfg.tenant_id, status="pending"))
                created += 1
    await db.flush()
    return created
