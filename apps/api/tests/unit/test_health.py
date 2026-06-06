"""Liveness/readiness + request-id middleware behavior."""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from chronosguard.api.health import readiness_checks

pytestmark = pytest.mark.anyio


class TestLiveness:
    async def test_healthz_returns_ok(self, client: AsyncClient) -> None:
        response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestReadiness:
    async def test_readyz_returns_ok_with_no_failing_checks(self, client: AsyncClient) -> None:
        response = await client.get("/readyz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    async def test_readyz_degrades_to_503_when_a_check_fails(
        self, client: AsyncClient, app: FastAPI
    ) -> None:
        async def failing_check() -> bool:
            return False

        readiness_checks["test_failing"] = failing_check
        try:
            response = await client.get("/readyz")
        finally:
            del readiness_checks["test_failing"]

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["test_failing"] == "failed"

    async def test_readyz_treats_raising_check_as_failed(self, client: AsyncClient) -> None:
        async def raising_check() -> bool:
            msg = "boom"
            raise RuntimeError(msg)

        readiness_checks["test_raising"] = raising_check
        try:
            response = await client.get("/readyz")
        finally:
            del readiness_checks["test_raising"]

        assert response.status_code == 503
        assert response.json()["checks"]["test_raising"] == "failed"


class TestRequestId:
    async def test_generates_request_id_when_absent(self, client: AsyncClient) -> None:
        response = await client.get("/healthz")
        assert len(response.headers["X-Request-ID"]) == 32

    async def test_echoes_caller_request_id(self, client: AsyncClient) -> None:
        response = await client.get("/healthz", headers={"X-Request-ID": "trace-me-123"})
        assert response.headers["X-Request-ID"] == "trace-me-123"
