"""Calendly integration — fetch upcoming events via API v2."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import httpx
from app.config import get_settings
from app.auth import require_user
from app.models import User

router = APIRouter(prefix="/calendly", tags=["calendly"])
templates_path = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

CALENDLY_API = "https://api.calendly.com"


async def fetch_calendly_events(api_key: str):
    # ponytail: single API call, no pagination — add when >20 events
    async with httpx.AsyncClient(timeout=10) as client:
        # Get user URI first
        r = await client.get(f"{CALENDLY_API}/users/me",
                             headers={"Authorization": f"Bearer {api_key}"})
        if r.status_code != 200:
            return {"error": f"Calendly API error: {r.status_code}", "events": []}
        user_uri = r.json()["resource"]["uri"]

        # Fetch scheduled events (upcoming)
        r = await client.get(
            f"{CALENDLY_API}/scheduled_events",
            params={"user": user_uri, "status": "active",
                    "sort": "start_time:ascending", "count": 20},
            headers={"Authorization": f"Bearer {api_key}"})
        events = []
        if r.status_code == 200:
            for ev in r.json().get("collection", []):
                invitee_name = "—"
                invitee_email = "—"
                # Fetch invitee for this event
                ev_uri = ev.get("uri", "")
                if ev_uri:
                    ir = await client.get(
                        f"{CALENDLY_API}/scheduled_event_invitations",
                        params={"scheduled_event": ev_uri, "count": 1},
                        headers={"Authorization": f"Bearer {api_key}"})
                    if ir.status_code == 200:
                        inv = ir.json().get("collection", [])
                        if inv:
                            invitee_name = inv[0].get("name", "—")
                            invitee_email = inv[0].get("email", "—")

                events.append({
                    "name": ev.get("name", "Meeting"),
                    "start": ev.get("start_time", ""),
                    "end": ev.get("end_time", ""),
                    "status": ev.get("status", "?"),
                    "event_type": ev.get("event_type", ""),
                    "invitee": invitee_name,
                    "email": invitee_email,
                })
        return {"events": events, "error": None}


@router.get("", response_class=HTMLResponse)
async def calendly_dashboard(
    request: Request,
    user: User = Depends(require_user),
):
    settings = get_settings()
    data = {"events": [], "error": "Not configured"}
    if settings.calendly_api_key:
        data = await fetch_calendly_events(settings.calendly_api_key)
    return templates.TemplateResponse("calendly_dashboard.html", {
        "request": request, "user": user,
        "events": data["events"], "error": data.get("error"),
        "calendly_url": "https://calendly.com/negotiatorsondemand/virtualcoffeewithdan",
    })
