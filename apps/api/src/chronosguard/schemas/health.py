"""Health/readiness response shapes."""

from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["ok", "failed"]


class HealthStatus(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessStatus(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, CheckStatus]
