"""GET /health and GET /api/v1/health: the same public liveness payload.

Railway probes /health. The status page probes /api/v1/health through the
same-origin /api proxy. Neither requires a login or a database.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_is_public_and_matches_on_both_paths():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        root = await client.get("/health")
        proxied = await client.get("/api/v1/health")

    assert root.status_code == 200
    assert proxied.status_code == 200
    assert root.json() == proxied.json()
    body = root.json()
    assert body["status"] == "healthy"
    assert isinstance(body["app"], str) and body["app"]
