import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from app.config import get_settings
from app.core.errors import AuthenticationError
from app.models.enums import UserRole

settings = get_settings()
password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


class TokenPayload(BaseModel):
    user_id: uuid.UUID
    role: UserRole | None = None
    token_type: str


def hash_password(plain_password: str) -> str:
    return password_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_context.verify(plain_password, hashed_password)


def _create_token(claims: dict, expires_in: timedelta) -> str:
    payload = claims | {"exp": datetime.now(timezone.utc) + expires_in}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, role: UserRole) -> str:
    """Carries the role so authentication needs no database query per request."""
    return _create_token(
        {"sub": str(user_id), "role": role.value, "type": ACCESS_TOKEN_TYPE},
        timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(user_id: uuid.UUID) -> str:
    """Carries no role: refreshing re-reads the user, which is where a
    deactivation or a role change takes effect."""
    return _create_token(
        {"sub": str(user_id), "type": REFRESH_TOKEN_TYPE},
        timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str) -> TokenPayload:
    try:
        claims = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise AuthenticationError() from exc

    role_claim = claims.get("role")
    return TokenPayload(
        user_id=uuid.UUID(claims["sub"]),
        role=UserRole(role_claim) if role_claim else None,
        token_type=claims.get("type", ""),
    )
