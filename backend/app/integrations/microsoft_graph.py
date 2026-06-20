"""Microsoft Graph API integration for Office 365 / Outlook.

Auth flow:
1. User clicks "Connect Microsoft 365" in UI -> /auth/microsoft/start
2. We redirect to Microsoft OAuth2 authorize URL with our app's client_id
3. User consents -> Microsoft redirects to /auth/microsoft/callback?code=...
4. We exchange code for access_token + refresh_token, store in email_accounts
5. Background job or webhook polls /me/messages for new mail

Setup:
1. Go to https://portal.azure.com -> Azure AD -> App registrations
2. New registration: name "Renter Portal", redirect URI: https://yourdomain/auth/microsoft/callback
3. API permissions: Mail.Read, offline_access, User.Read
4. Generate client secret, save in env vars MS_CLIENT_ID, MS_CLIENT_SECRET
"""

import os
import re
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from urllib.parse import urlencode
import httpx


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


def get_authorize_url(client_id: str, redirect_uri: str, state: str = "") -> str:
    """Generate the OAuth2 authorize URL."""
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": "offline_access Mail.Read User.Read",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(
    client_id: str, client_secret: str, code: str, redirect_uri: str
) -> Dict[str, Any]:
    """Exchange auth code for access + refresh tokens."""
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "scope": "offline_access Mail.Read User.Read",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(TOKEN_URL, data=data)
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(
    client_id: str, client_secret: str, refresh_token: str
) -> Dict[str, Any]:
    """Refresh an expired access token."""
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": "offline_access Mail.Read User.Read",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(TOKEN_URL, data=data)
        resp.raise_for_status()
        return resp.json()


def token_expiry(expires_in: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in - 300)


async def fetch_user_profile(access_token: str) -> Dict[str, str]:
    """Get the connected user's email + display name."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GRAPH_BASE}/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        return {"email": data.get("mail") or data.get("userPrincipalName", ""),
                "name": data.get("displayName", "")}


async def list_messages(
    access_token: str,
    folder: str = "inbox",
    top: int = 50,
    delta_token: Optional[str] = None,
    filter_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch recent messages. Uses delta query if delta_token provided for incremental sync."""
    if delta_token:
        url = delta_token  # delta URL
    else:
        url = f"{GRAPH_BASE}/me/mailFolders/{folder}/messages"
        params = {
            "$top": top,
            "$select": "id,subject,from,receivedDateTime,bodyPreview,isRead",
            "$orderby": "receivedDateTime DESC",
        }
        if filter_date:
            params["$filter"] = f"receivedDateTime ge {filter_date}"
        url = f"{url}?{urlencode(params)}"
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


def parse_graph_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Convert Graph API message format to our internal schema."""
    sender = msg.get("from", {}).get("emailAddress", {})
    return {
        "external_id": msg["id"],
        "subject": msg.get("subject", ""),
        "sender_email": sender.get("address", ""),
        "sender_name": sender.get("name", ""),
        "received_at": msg.get("receivedDateTime"),
        "body_preview": msg.get("bodyPreview", "")[:500],
        "is_read": msg.get("isRead", False),
    }
