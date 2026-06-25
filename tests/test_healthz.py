"""Smoke test: /healthz returns 200 with status ok."""

from httpx import ASGITransport, AsyncClient

from claimpilot.api.main import app


async def test_healthz_returns_ok() -> None:
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz_returns_ready() -> None:
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/readyz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}
