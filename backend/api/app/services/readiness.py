"""Can this task reach what it depends on?"""

import time
from collections.abc import Callable, Sequence
from typing import Any

from app.core.errors import AppError
from app.core.logging import get_logger
from app.services.ports import DependencyProbe

logger = get_logger(__name__)


class ReadinessService:
    # /ready is unauthenticated and each check is an AWS call, so results are
    # cached: an uptime checker polling it must not become a cost or a
    # throttling source.
    CACHE_SECONDS = 15.0

    def __init__(self, probes: Sequence[DependencyProbe], clock: Callable[[], float] = time.monotonic) -> None:
        self._probes = probes
        self._clock = clock
        self._cached: tuple[float, dict[str, Any]] | None = None

    def report(self) -> dict[str, Any]:
        now = self._clock()
        if self._cached is None or now - self._cached[0] >= self.CACHE_SECONDS:
            checks = [self._run(p) for p in self._probes]
            status = "ok" if all(c["status"] == "ok" for c in checks) else "degraded"
            self._cached = (now, {"status": status, "checks": checks})
        return self._cached[1]

    def _run(self, probe: DependencyProbe) -> dict[str, Any]:
        started = time.perf_counter()
        result: dict[str, Any] = {"name": probe.name, "status": "ok"}
        try:
            probe.check()
        except Exception as exc:  # noqa: BLE001 - a probe reports, it never raises
            code = exc.code if isinstance(exc, AppError) else "internal_error"
            logger.warning("readiness_probe_failed", probe=probe.name, code=code,
                           detail=getattr(exc, "detail", None) or repr(exc))
            # The code only: this endpoint is reachable without authentication.
            result = {"name": probe.name, "status": "unavailable", "code": code}
        result["latencyMs"] = round((time.perf_counter() - started) * 1000, 2)
        return result
