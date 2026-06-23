"""Negotiation Trainer — Mix & Match card game web app."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pathlib import Path

router = APIRouter(tags=["trainer"])
templates_path = Path(__file__).parent.parent / "templates"

# ponytail: /trainer route (trainer.html doesn't exist) — serves mixmatch from templates
# The upstream route expects templates/trainer.html; we don't have that file.
# Redirect /trainer → /mixmatch so the URL works from the trainer menu.
@router.get("/trainer", response_class=HTMLResponse)
async def trainer_page(request: Request):
    return templates_path.joinpath("mixmatch.html").read_text()
