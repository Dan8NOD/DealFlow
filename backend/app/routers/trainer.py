"""Negotiation Trainer — Mix & Match card game web app."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pathlib import Path

router = APIRouter(tags=["trainer"])
templates_path = Path(__file__).parent.parent / "templates"

# ponytail: /nodify route — serves mixmatch from templates
@router.get("/nodify", response_class=HTMLResponse)
async def trainer_page(request: Request):
    return templates_path.joinpath("mixmatch.html").read_text()
