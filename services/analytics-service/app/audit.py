import logging
import os
import jwt
from app.database import SessionLocal
from app.models import AuditLog
logger = logging.getLogger(__name__)
SECRET_KEY = os.getenv("AUTH_SECRET_KEY")
ALGORITHM = "HS256"
def get_user_id(authorization: str | None) -> int | None:
    if not authorization or not SECRET_KEY:
        return None
    try:
        scheme, token = authorization.split(" ", 1)
        if scheme.lower() != "bearer":
            return None
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
        )
        if payload.get("type") != "access":
            return None
        return int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, KeyError):
        return None
def record_audit(
    action: str,
    details: str,
    ip_address: str | None = None,
    user_id: int | None = None,
):
    db = SessionLocal()
    try:
        audit = AuditLog(
            user_id=user_id,
            action=action,
            resource_type="analytics_report",
            resource_id=action,
            status="success",
            details=details[:500],
            ip_address=ip_address,
        )
        db.add(audit)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Analytics audit logging failed")
    finally:
        db.close()
