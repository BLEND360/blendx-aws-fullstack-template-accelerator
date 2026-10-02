from functools import cache

from fastapi import APIRouter, Depends, Response

from app.clients.aws import HarnessProbe, TableProbe
from app.core.config import settings
from app.services.readiness import ReadinessService

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness, and the ALB health check. Touches no dependency on purpose:
    if it failed whenever AgentCore was degraded, the ALB would drain every
    task and turn a partial outage into a total one."""
    return {"status": "ok"}


@cache
def readiness_service() -> ReadinessService:
    return ReadinessService(
        [
            HarnessProbe(settings.harness_arn),
            TableProbe(settings.sessions_table_name),
            TableProbe(settings.items_table_name),
        ]
    )


@router.get("/ready")
def ready(response: Response, service: ReadinessService = Depends(readiness_service)) -> dict:
    """503 when a dependency is unreachable, so an uptime check can alert on it
    while /health keeps the tasks in service."""
    report = service.report()
    if report["status"] != "ok":
        response.status_code = 503
    return report
