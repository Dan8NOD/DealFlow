"""
Obsidian API — sync status, scan vault, link notes to properties.
"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.auth import get_current_user
from app.models import User
from app.obsidian_sync import scan_all_vaults, sync_to_db, parse_obsidian_note

router = APIRouter(prefix="/api/obsidian", tags=["obsidian"])


@router.get("/scan")
async def scan_vaults(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Scan all Obsidian vaults and return parsed notes."""
    notes = scan_all_vaults()
    return {
        "count": len(notes),
        "notes": notes,
    }


@router.post("/sync")
async def sync_obsidian(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Scan and sync Obsidian notes to the database."""
    import os
    from app.config import get_settings
    settings = get_settings()

    # Find the SQLite DB path
    db_path = settings.database_url.replace("sqlite:///", "")
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.getcwd(), db_path)

    notes = scan_all_vaults()
    stats = sync_to_db(notes, db_path)

    return {
        "scanned": len(notes),
        "stats": stats,
    }


@router.get("/status")
async def obsidian_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get sync status: how many Obsidian notes matched to properties."""
    from app.models import PropertyFile
    total = db.query(PropertyFile).filter(
        PropertyFile.org_id == user.org_id,
        PropertyFile.source == "obsidian",
    ).count()
    matched = db.query(PropertyFile).filter(
        PropertyFile.org_id == user.org_id,
        PropertyFile.source == "obsidian",
        PropertyFile.property_id.isnot(None),
    ).count()

    return {
        "total_obsidian_notes": total,
        "matched_to_properties": matched,
        "unmatched": total - matched,
    }