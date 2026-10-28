from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import get_db
from app.models import User
from app.security import decode_token

SYS_ADMIN = "sysAdmin"
ADMIN = "admin"
USER = "user"

PERMISSIONS = {
    SYS_ADMIN: {
        "company:manage", "user:manage", "audit:read",
        "graph:read", "graph:write",
    },
    ADMIN: {"user:manage", "audit:read", "graph:read", "graph:write"},
    USER: {"graph:read", "graph:write"},
}

_bearer = HTTPBearer(auto_error=False)


def unauthorized():
    return HTTPException(401, "Unauthorized access")


def forbidden():
    return HTTPException(403, "Unauthorized access")


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db=Depends(get_db),
) -> User:
    claims = decode_token(creds.credentials) if creds else None
    if not claims:
        raise unauthorized()
    user = db.get(User, int(claims["sub"]))
    if not user or not user.active:
        raise unauthorized()
    if user.company and not user.company.active:
        raise unauthorized()
    return user


def require_permission(permission: str):
    def check(user: User = Depends(get_current_user)) -> User:
        if permission not in PERMISSIONS.get(user.role, set()):
            raise forbidden()
        return user

    return check


def scoped(query, user: User, column=User.company_id):
    """Company isolation: only sysAdmin sees across companies."""
    if user.role == SYS_ADMIN:
        return query
    return query.where(column == user.company_id)
