import pytest


@pytest.mark.asyncio
async def test_admin_creates_a_user(http_client, admin_user, auth_headers_for):
    response = await http_client.post(
        "/api/v1/users",
        headers=auth_headers_for(admin_user),
        json={
            "email": "new.person@example.com",
            "full_name": "New Person",
            "password": "a-long-enough-password",
            "role": "team_member",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.person@example.com"
    assert "password" not in body
    assert "hashed_password" not in body


@pytest.mark.asyncio
async def test_duplicate_email_is_rejected(http_client, admin_user, auth_headers_for):
    payload = {
        "email": "duplicate@example.com",
        "full_name": "First",
        "password": "a-long-enough-password",
        "role": "team_member",
    }
    first = await http_client.post(
        "/api/v1/users", headers=auth_headers_for(admin_user), json=payload
    )
    assert first.status_code == 201

    second = await http_client.post(
        "/api/v1/users", headers=auth_headers_for(admin_user), json=payload
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_short_password_is_rejected(http_client, admin_user, auth_headers_for):
    response = await http_client.post(
        "/api/v1/users",
        headers=auth_headers_for(admin_user),
        json={
            "email": "short@example.com",
            "full_name": "Short Password",
            "password": "tiny",
            "role": "team_member",
        },
    )
    assert response.status_code == 422
