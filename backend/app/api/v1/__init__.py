from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    audit,
    auth,
    correlation_config,
    graph,
    groups,
    incidents,
    ingest,
    notification_admin,
    notifications,
    rule_groups,
    rules,
    servers,
    stats,
    sync,
    tenants,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(groups.router)
api_router.include_router(servers.router)
api_router.include_router(rules.router)
api_router.include_router(rule_groups.router)
api_router.include_router(notifications.router)
api_router.include_router(alerts.router)
api_router.include_router(ingest.router)
api_router.include_router(incidents.router)
api_router.include_router(correlation_config.router)
api_router.include_router(notification_admin.router)
api_router.include_router(stats.router)
api_router.include_router(graph.router)
api_router.include_router(sync.router)
api_router.include_router(audit.router)
api_router.include_router(tenants.router)
