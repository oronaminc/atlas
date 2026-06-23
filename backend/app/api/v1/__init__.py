from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    audit,
    auth,
    channels,
    graph,
    group_codes,
    grouping_rules,
    groups,
    incidents,
    ingest,
    labels,
    llm_config,
    mimir_query_config,
    notification_admin,
    notification_defaults,
    notifications,
    retention_config,
    rules,
    search,
    silences,
    stats,
    threshold_overrides,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(channels.router)
api_router.include_router(users.router)
api_router.include_router(groups.router)
api_router.include_router(rules.router)
api_router.include_router(labels.router)
api_router.include_router(silences.router)
api_router.include_router(notifications.router)
api_router.include_router(alerts.router)
api_router.include_router(ingest.router)
api_router.include_router(incidents.router)
api_router.include_router(retention_config.router)
api_router.include_router(notification_admin.router)
api_router.include_router(stats.router)
api_router.include_router(graph.router)
api_router.include_router(audit.router)
api_router.include_router(llm_config.router)
api_router.include_router(mimir_query_config.router)
api_router.include_router(search.router)
api_router.include_router(threshold_overrides.router)
api_router.include_router(grouping_rules.router)
api_router.include_router(notification_defaults.router)
api_router.include_router(group_codes.router)
