import pytest


@pytest.mark.asyncio
async def test_request_without_a_token_is_rejected(http_client):
    response = await http_client.get("/api/v1/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_team_member_cannot_reach_an_admin_route(
    http_client, team_member_user, auth_headers_for
):
    response = await http_client.post(
        "/api/v1/service-types",
        json={"name": "Attempted by a team member"},
        headers=auth_headers_for(team_member_user),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_reach_an_admin_route(http_client, admin_user, auth_headers_for):
    response = await http_client.post(
        "/api/v1/service-types",
        json={"name": "Created by an admin"},
        headers=auth_headers_for(admin_user),
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_any_authenticated_role_can_read_the_user_directory(
    http_client, team_member_user, auth_headers_for
):
    """The listing is a staff directory: every role needs it to render names,
    and a manager needs it to choose an assignee. Creating and updating users
    stay admin-only.
    """
    response = await http_client.get(
        "/api/v1/users", headers=auth_headers_for(team_member_user)
    )
    assert response.status_code == 200
