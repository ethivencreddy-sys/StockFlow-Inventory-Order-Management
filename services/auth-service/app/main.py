
from datetime import datetime, timedelta, timezone

import jwt

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    status,
)
from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials,
)
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db

from app.models import (
    AuditLog,
    RefreshToken,
    User,
)

from app.schemas import (
    RefreshRequest,
    RoleUpdate,
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
)

from app.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Authentication Service", version="1.1.0")

bearer_scheme = HTTPBearer()

REFRESH_TOKEN_EXPIRE_DAYS = 7

ALLOWED_ROLES = {
    "customer",
    "administrator",
    "inventory_manager",
}


# --------------------------------------------------
# AUDIT LOGGING
# --------------------------------------------------

def record_audit(
    db: Session,
    request: Request,
    action: str,
    resource_type: str,
    user_id: int | None = None,
    resource_id: str | None = None,
    event_status: str = "success",
    details: str | None = None,
):
    """
    Store an audit event without recording passwords,
    JWTs, refresh tokens, or other authentication secrets.
    """

    try:
        ip_address = (
            request.client.host
            if request.client
            else None
        )

        audit = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status=event_status,
            details=details,
            ip_address=ip_address,
        )

        db.add(audit)
        db.commit()

    except Exception as exc:
        db.rollback()

        # An audit failure should not expose secrets or
        # prevent the authentication endpoint from working.
        print(
            f"Audit logging failed: {type(exc).__name__}",
            flush=True,
        )


# --------------------------------------------------
# TOKEN MANAGEMENT
# --------------------------------------------------

def issue_tokens(user: User, db: Session) -> TokenResponse:

    raw_refresh_token = create_refresh_token()

    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    )

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh_token),
            expires_at=expires_at.replace(tzinfo=None),
            revoked=0,
        )
    )

    db.commit()

    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=raw_refresh_token,
    )


# --------------------------------------------------
# AUTHENTICATION
# --------------------------------------------------

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])

    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise unauthorized

    user = db.query(User).filter(User.id == user_id).first()

    if (
        not user
        or not user.is_active
        or user.role != payload.get("role")
    ):
        raise unauthorized

    return user


def require_roles(*roles: str):

    def role_checker(
        user: User = Depends(get_current_user),
    ) -> User:

        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )

        return user

    return role_checker


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.get("/health")
def health():

    return {
        "status": "healthy",
        "service": "auth-service",
    }


# --------------------------------------------------
# USER REGISTRATION
# --------------------------------------------------

@app.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    data: UserRegister,
    request: Request,
    db: Session = Depends(get_db),
):

    email = data.email.lower()

    existing = (
        db.query(User)
        .filter(User.email == email)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    user = User(
        username=data.username,
        email=email,
        hashed_password=hash_password(data.password),
        role="customer",
        is_active=1,
    )

    db.add(user)

    try:
        db.commit()
        db.refresh(user)

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not register user; check whether the email exists",
        )

    record_audit(
        db=db,
        request=request,
        action="user_registered",
        resource_type="user",
        user_id=user.id,
        resource_id=str(user.id),
        details="New customer account registered",
    )

    return user


# --------------------------------------------------
# USER LOGIN
# --------------------------------------------------

@app.post("/auth/login", response_model=TokenResponse)
def login(
    data: UserLogin,
    request: Request,
    db: Session = Depends(get_db),
):

    user = (
        db.query(User)
        .filter(User.email == data.email.lower())
        .first()
    )

    if (
        not user
        or not user.is_active
        or not verify_password(
            data.password,
            user.hashed_password,
        )
    ):

        record_audit(
            db=db,
            request=request,
            action="login_failed",
            resource_type="authentication",
            user_id=user.id if user else None,
            event_status="failure",
            details="Invalid credentials or inactive account",
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    tokens = issue_tokens(user, db)

    record_audit(
        db=db,
        request=request,
        action="login_success",
        resource_type="authentication",
        user_id=user.id,
        resource_id=str(user.id),
        details="User logged in successfully",
    )

    return tokens


# --------------------------------------------------
# REFRESH ACCESS TOKEN
# --------------------------------------------------

@app.post("/auth/refresh", response_model=TokenResponse)
def refresh(
    data: RefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
):

    token_hash = hash_refresh_token(data.refresh_token)

    stored = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash)
        .first()
    )

    if not stored or stored.revoked:

        record_audit(
            db=db,
            request=request,
            action="refresh_failed",
            resource_type="authentication",
            event_status="failure",
            details="Invalid or revoked refresh token",
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if stored.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):

        stored.revoked = 1
        db.commit()

        record_audit(
            db=db,
            request=request,
            action="refresh_failed",
            resource_type="authentication",
            user_id=stored.user_id,
            event_status="failure",
            details="Refresh token expired",
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        )

    user = (
        db.query(User)
        .filter(User.id == stored.user_id)
        .first()
    )

    if not user or not user.is_active:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is unavailable",
        )

    # Revoke the old refresh token before issuing a new one.
    stored.revoked = 1
    db.commit()

    tokens = issue_tokens(user, db)

    record_audit(
        db=db,
        request=request,
        action="token_refreshed",
        resource_type="authentication",
        user_id=user.id,
        resource_id=str(user.id),
        details="Access and refresh tokens rotated",
    )

    return tokens


# --------------------------------------------------
# CURRENT USER
# --------------------------------------------------

@app.get("/auth/me", response_model=UserResponse)
def me(
    user: User = Depends(get_current_user),
):

    return user


# --------------------------------------------------
# ADMIN: UPDATE USER ROLE
# --------------------------------------------------

@app.patch(
    "/auth/users/{user_id}/role",
    response_model=UserResponse,
)
def update_user_role(
    user_id: int,
    data: RoleUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("administrator")),
):

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    old_role = user.role

    user.role = data.role

    try:
        db.commit()
        db.refresh(user)

    except Exception:
        db.rollback()
        raise

    record_audit(
        db=db,
        request=request,
        action="user_role_updated",
        resource_type="user",
        user_id=admin.id,
        resource_id=str(user.id),
        details=f"Role changed from {old_role} to {user.role}",
    )

    return user
