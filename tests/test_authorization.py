import pytest


@pytest.mark.asyncio
async def test_request_without_a_token_is_rejected(http_client):
    response = await http_client.get("/api/v1/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_team_member_cannot_reach_an_admin_route(
    http_client, team_member_user, auth_headers_for
):
    response = await http_client.get(
        "/api/v1/users", headers=auth_headers_for(team_member_user)
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_reach_an_admin_route(http_client, admin_user, auth_headers_for):
    response = await http_client.get(
        "/api/v1/users", headers=auth_headers_for(admin_user)
    )
    assert response.status_code == 200
