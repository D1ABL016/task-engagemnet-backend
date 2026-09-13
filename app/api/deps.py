import uuid
from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.models.enums import UserRole

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    role: UserRole

    @property
    def is_manager_or_admin(self) -> bool:
        return self.role in (UserRole.MANAGER, UserRole.ADMIN)

    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    """Reads identity from the token's claims and does not query the database.

    Authentication costs a signature verification and nothing else. The trade is
    staleness: a deactivated or demoted user keeps their access until the token
    expires, which the 15-minute lifetime bounds.
    """
    if credentials is None:
        raise AuthenticationError("Missing bearer token")

    payload = decode_token(credentials.credentials)
    if payload.token_type != ACCESS_TOKEN_TYPE:
        raise AuthenticationError("Not an access token")
    if payload.role is None:
        raise AuthenticationError("Token carries no role")

    return CurrentUser(id=payload.user_id, role=payload.role)


def require_roles(*allowed_roles: UserRole):
    """Coarse role filter for a route.

    Relational rules — is this actor *this task's* reviewer — cannot be checked
    here, because they need the row. Those live in the service layer.
    """

    async def dependency(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise PermissionDeniedError(
                f"Requires one of: {', '.join(role.value for role in allowed_roles)}"
            )
        return current_user

    return dependency


require_admin = require_roles(UserRole.ADMIN)
require_manager = require_roles(UserRole.MANAGER, UserRole.ADMIN)
require_any_role = require_roles(UserRole.ADMIN, UserRole.MANAGER, UserRole.TEAM_MEMBER)
