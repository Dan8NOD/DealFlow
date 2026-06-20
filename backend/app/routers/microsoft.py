"""Microsoft 365 OAuth + sync routes."""
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db, SessionLocal
from app.auth import get_current_user
from app.config import get_settings
from app.models import User, EmailAccount
from app.integrations import microsoft_graph as graph
from app.integrations.sync_engine import sync_account, sync_org

router = APIRouter(prefix="/auth/microsoft", tags=["microsoft"])
settings = get_settings()


@router.get("/start")
async def ms_start(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Redirect user to Microsoft OAuth2 authorize screen."""
    if not settings.ms_client_id:
        return HTMLResponse(
            "<h1>Microsoft 365 not configured</h1>"
            "<p>Set MS_CLIENT_ID and MS_CLIENT_SECRET in your .env file, "
            "then register the app in Azure AD with the redirect URI: "
            f"<code>{settings.ms_redirect_uri}</code></p>"
            "<p>See <a href='https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps'>Azure AD App Registrations</a></p>",
            status_code=500,
        )
    state = secrets.token_urlsafe(16)
    # Store state in session cookie for CSRF check
    url = graph.get_authorize_url(settings.ms_client_id, settings.ms_redirect_uri, state)
    resp = RedirectResponse(url=url, status_code=303)
    resp.set_cookie("ms_oauth_state", state, httponly=True, max_age=600)
    return resp


@router.get("/callback")
async def ms_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """OAuth callback - Microsoft redirects here after user consent."""
    expected_state = request.cookies.get("ms_oauth_state")
    if not expected_state or expected_state != state:
        return JSONResponse({"error": "state mismatch"}, status_code=400)
    # Exchange code for tokens
    token = await graph.exchange_code_for_tokens(
        settings.ms_client_id, settings.ms_client_secret,
        code, settings.ms_redirect_uri,
    )
    # Fetch user profile
    profile = await graph.fetch_user_profile(token["access_token"])
    # Find or create user (assume first user of org if no session)
    user_email = profile["email"]
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        # The user might not exist yet; create one if not
        from app.models import UserRole
        from app.auth import hash_password
        import secrets as _secrets
        user = User(
            org_id=1,  # default to first org if not found
            email=user_email,
            password_hash=hash_password(_secrets.token_urlsafe(16)),
            full_name=profile["name"] or user_email,
            role=UserRole.MEMBER,
        )
        db.add(user)
        db.flush()
    # Create or update EmailAccount
    account = db.query(EmailAccount).filter(
        EmailAccount.org_id == user.org_id,
        EmailAccount.email_address == user_email,
    ).first()
    if account:
        account.access_token = token["access_token"]
        account.refresh_token = token.get("refresh_token", account.refresh_token)
        account.token_expires_at = graph.token_expiry(token["expires_in"])
        account.is_active = True
    else:
        account = EmailAccount(
            org_id=user.org_id,
            user_id=user.id,
            provider="microsoft",
            email_address=user_email,
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token"),
            token_expires_at=graph.token_expiry(token["expires_in"]),
            is_active=True,
        )
        db.add(account)
    db.commit()
    # Redirect to dashboard with success message
    resp = RedirectResponse(url="/dashboard?ms_connected=1", status_code=303)
    resp.delete_cookie("ms_oauth_state")
    return resp


@router.get("/disconnect")
async def ms_disconnect(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(EmailAccount).filter(
        EmailAccount.org_id == user.org_id,
        EmailAccount.email_address == user.email,
        EmailAccount.is_active == True,
    ).first()
    if account:
        account.is_active = False
        account.access_token = None
        db.commit()
    return RedirectResponse(url="/dashboard?ms_disconnected=1", status_code=303)
