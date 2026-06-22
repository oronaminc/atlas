"""Read-only view of the live Mimir Ruler rules (IMP: rules are pull-only).

atlas no longer owns alert rules — it reads them from the Ruler so an operator
can pick an alertname and attach a threshold override to it (Thresholds page).
Single default org (X-Scope-OrgID via make_client). No DB; no mutation."""

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_current_user
from app.core.envelope import envelope
from app.integrations.mimir_ruler import MimirRulerClient
from app.models import User
from app.schemas.rule import PulledRuleOut

router = APIRouter(prefix="/rules", tags=["rules"])


def get_ruler_client() -> MimirRulerClient:
    """Injectable Ruler client (default org); tests override this."""
    return MimirRulerClient()


def _flatten(namespaces: dict) -> list[PulledRuleOut]:
    out: list[PulledRuleOut] = []
    for namespace, groups in (namespaces or {}).items():
        for group in groups or []:
            for rule in group.get("rules", []) or []:
                alertname = rule.get("alert")
                if not alertname:  # skip recording rules (have `record`, no `alert`)
                    continue
                labels = rule.get("labels", {}) or {}
                out.append(
                    PulledRuleOut(
                        alertname=alertname,
                        expr=rule.get("expr", ""),
                        for_=rule.get("for"),
                        severity=labels.get("severity"),
                        labels=labels,
                        annotations=rule.get("annotations", {}) or {},
                        namespace=str(namespace),
                        group=group.get("name", ""),
                    )
                )
    return out


@router.get("/pulled")
async def pulled_rules(
    _: User = Depends(get_current_user),
    ruler: MimirRulerClient = Depends(get_ruler_client),
):
    """Live alerting rules from the Ruler, flattened to one entry per alert."""
    try:
        namespaces = await ruler.get_all_rules()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ruler unreachable: {exc}") from exc
    finally:
        await ruler.aclose()
    return envelope([r.model_dump(mode="json", by_alias=True) for r in _flatten(namespaces)])
