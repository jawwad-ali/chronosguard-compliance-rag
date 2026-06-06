"""Error contract: every failure path returns one ProblemDetail shape."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from chronosguard.core.errors import PROBLEM_CONTENT_TYPE, NotFoundError

pytestmark = pytest.mark.anyio


class _EchoBody(BaseModel):
    name: str
    count: int


@pytest.fixture
def app_with_test_routes(app: FastAPI) -> FastAPI:
    @app.get("/boom-domain")
    async def boom_domain() -> None:
        raise NotFoundError("Policy", 42)

    @app.get("/boom-unhandled")
    async def boom_unhandled() -> None:
        msg = "unexpected internal failure with secret details"
        raise RuntimeError(msg)

    @app.post("/echo")
    async def echo(body: _EchoBody) -> _EchoBody:
        return body

    return app


@pytest.fixture
async def client(app_with_test_routes: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app_with_test_routes, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


class TestProblemShape:
    async def test_unknown_route_returns_problem_json(self, client: AsyncClient) -> None:
        response = await client.get("/definitely-not-a-route")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
        body = response.json()
        assert body["status"] == 404
        assert body["request_id"]

    async def test_domain_error_maps_to_status_and_detail(self, client: AsyncClient) -> None:
        response = await client.get("/boom-domain")
        assert response.status_code == 404
        body = response.json()
        assert body["title"] == "Not Found"
        assert body["detail"] == "Policy not found: 42"
        assert body["instance"] == "/boom-domain"

    async def test_validation_error_carries_field_errors(self, client: AsyncClient) -> None:
        response = await client.post("/echo", json={"name": 7})
        assert response.status_code == 422
        body = response.json()
        assert body["title"] == "Validation Error"
        locs = {err["loc"] for err in body["errors"]}
        assert "body.count" in locs

    async def test_unhandled_error_never_leaks_internals(self, client: AsyncClient) -> None:
        response = await client.get("/boom-unhandled")
        assert response.status_code == 500
        body = response.json()
        assert body["title"] == "Internal Server Error"
        assert "secret" not in response.text
        assert "RuntimeError" not in response.text
