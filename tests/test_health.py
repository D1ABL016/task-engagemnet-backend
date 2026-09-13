import pytest


@pytest.mark.asyncio
async def test_health_check_returns_ok(http_client):
    response = await http_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
