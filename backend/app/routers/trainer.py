"""Negotiation Trainer — Mix & Match asset dashboard."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session
from app.db import get_db
from app.auth import require_user
from app.models import User

router = APIRouter(tags=["trainer"])
templates_path = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

# ponytail: /nodify serves the full MixMatch SPA behind auth (asset dashboard + trainer)
@router.get("/nodify", response_class=HTMLResponse)
async def nodify_asset_page(
    request: Request,
    user: User = Depends(require_user),
):
    return templates.TemplateResponse("mixmatch.html", {
        "request": request,
        "user": user,
    })
