import pytest

from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.models.enums import UserRole


def test_password_round_trips():
    hashed = hash_password("correct-horse-battery")
    assert hashed != "correct-horse-battery"
    assert verify_password("correct-horse-battery", hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_token_carries_role(admin_user):
    token = create_access_token(admin_user.id, UserRole.ADMIN)
    payload = decode_token(token)
    assert payload.user_id == admin_user.id
    assert payload.role == UserRole.ADMIN
    assert payload.token_type == "access"


@pytest.mark.asyncio
async def test_login_returns_tokens(http_client, team_member_user):
    response = await http_client.post(
        "/api/v1/auth/login",
        json={"email": team_member_user.email, "password": "test-password"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]


@pytest.mark.asyncio
async def test_login_with_wrong_password_is_rejected(http_client, team_member_user):
    response = await http_client.post(
        "/api/v1/auth/login",
        json={"email": team_member_user.email, "password": "not-the-password"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_with_malformed_email_is_rejected(http_client):
    response = await http_client.post(
        "/api/v1/auth/login",
        json={"email": "not-an-email", "password": "irrelevant"},
    )
    assert response.status_code == 422
