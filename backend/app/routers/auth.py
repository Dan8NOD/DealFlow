"""Auth routes: signup, login, logout."""
from fastapi import APIRouter, Depends, HTTPException, Response, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import Organization, User, PlanTier, UserRole
from app.auth import hash_password, verify_password, create_access_token, get_current_user
from app.config import get_settings
from datetime import datetime, timezone

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.post("/signup")
async def signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    org_name: str = Form(""),
    db: Session = Depends(get_db),
):
    email = email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be 8+ chars")
    if not org_name:
        org_name = email.split("@")[0].title() + " Realty"
    org = Organization(name=org_name, plan=PlanTier.FREE)
    db.add(org)
    db.flush()
    user = User(
        org_id=org.id,
        email=email,
        password_hash=hash_password(password),
        full_name=full_name or email,
        role=UserRole.OWNER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id, user.org_id, user.role.value)
    response = RedirectResponse(url="/nod", status_code=303)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=settings.access_token_minutes * 60,
        samesite="lax",
        secure=(settings.environment == "production"),
    )
    return response


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.lower().strip()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    token = create_access_token(user.id, user.org_id, user.role.value)
    response = RedirectResponse(url="/nod", status_code=303)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=settings.access_token_minutes * 60,
        samesite="lax",
        secure=(settings.environment == "production"),
    )
    return response


@router.post("/logout")
async def logout(response: Response):
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("session_token")
    return response
