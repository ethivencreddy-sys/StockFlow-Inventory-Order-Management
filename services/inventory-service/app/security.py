
import os

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


SECRET_KEY = os.getenv("AUTH_SECRET_KEY")

if not SECRET_KEY:
    raise RuntimeError(
        "AUTH_SECRET_KEY environment variable is not set."
    )

ALGORITHM = "HS256"

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    try:
        payload = jwt.decode(
            credentials.credentials,
            SECRET_KEY,
            algorithms=[ALGORITHM],
        )

        if payload.get("type") != "access":
            raise jwt.InvalidTokenError("Invalid token type")

        user_id = int(payload["sub"])
        role = payload["role"]

        if user_id <= 0 or not isinstance(role, str):
            raise jwt.InvalidTokenError("Invalid user claims")

        return {
            "user_id": user_id,
            "role": role,
        }

    except (
        jwt.InvalidTokenError,
        ValueError,
        KeyError,
        TypeError,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_roles(*roles: str):
    def role_checker(
        user: dict = Depends(get_current_user),
    ) -> dict:
        if user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return role_checker
