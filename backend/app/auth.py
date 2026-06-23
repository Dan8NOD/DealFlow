"""Auth: password hashing + JWT tokens + session helpers."""
from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, Request, Cookie
from sqlalchemy.orm import Session
from app.config import get_settings
from app.db import get_db
from app.models import User, Organization

settings = get_settings()


def hash_password(password: str) -> str:
    # bcrypt has a 72-byte limit; truncate if needed
    pwd_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        pwd_bytes = plain.encode("utf-8")[:72]
        return bcrypt.checkpw(pwd_bytes, hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: int, org_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    payload = {"sub": str(user_id), "org_id": org_id, "role": role, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except JWTError:
        return None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    session_token: Optional[str] = Cookie(None),
) -> User:
    token = session_token
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def require_user(
    request: Request,
    db: Session = Depends(get_db),
    session_token: Optional[str] = Cookie(None),
) -> "User":
    # ponytail: browser dep that redirects to /login instead of raising 401 JSON
    from fastapi.responses import RedirectResponse
    token = session_token or request.headers.get("Authorization", "")[7:]
    if not token:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    user = db.query(User).filter(User.id == payload.get("sub"), User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return user


def get_current_org(user: User = Depends(get_current_user)) -> Organization:
    return user.organization
