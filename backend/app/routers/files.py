"""
File browser API — Google Drive + Obsidian + iCloud files linked to properties.
"""
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.db import get_db
from app.auth import get_current_user
from app.models import User, Property, PropertyFile

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/property/{property_id}")
async def property_files(
    property_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all files linked to a property — from Obsidian, Google Drive, iCloud."""
    files = db.query(PropertyFile).filter(
        PropertyFile.property_id == property_id,
        PropertyFile.org_id == user.org_id,
    ).order_by(PropertyFile.kind, PropertyFile.name).all()

    return [{
        "id": f.id, "kind": f.kind, "name": f.name,
        "source": f.source, "path": f.path,
        "section": f.section, "obsidian_vault": f.obsidian_vault,
        "size_bytes": f.size_bytes,
    } for f in files]


@router.get("/all")
async def all_property_files(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    source: str = Query(None),  # 'obsidian', 'gdrive', 'icloud'
    section: str = Query(None),  # 'LEASING', 'SALES'
    limit: int = Query(200, le=500),
):
    """List all property files across all properties."""
    q = db.query(PropertyFile).filter(PropertyFile.org_id == user.org_id)
    if source:
        q = q.filter(PropertyFile.source == source)
    if section:
        q = q.filter(PropertyFile.section == section)
    files = q.order_by(desc(PropertyFile.created_at)).limit(limit).all()

    # Get property addresses
    prop_ids = {f.property_id for f in files}
    props = {p.id: p for p in db.query(Property).filter(Property.id.in_(prop_ids)).all()}

    return [{
        "id": f.id, "property_id": f.property_id,
        "property_address": f"{props[f.property_id].address} #{props[f.property_id].unit}" if f.property_id in props and props[f.property_id].unit else (props[f.property_id].address if f.property_id in props else ""),
        "kind": f.kind, "name": f.name, "source": f.source,
        "path": f.path, "section": f.section,
        "obsidian_vault": f.obsidian_vault,
        "size_bytes": f.size_bytes,
    } for f in files]


@router.get("/stats")
async def file_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """File statistics by source."""
    from sqlalchemy import func
    rows = db.query(
        PropertyFile.source,
        func.count(PropertyFile.id).label('count')
    ).filter(
        PropertyFile.org_id == user.org_id
    ).group_by(PropertyFile.source).all()

    by_section = db.query(
        PropertyFile.section,
        func.count(PropertyFile.id).label('count')
    ).filter(
        PropertyFile.org_id == user.org_id
    ).group_by(PropertyFile.section).all()

    return {
        "total": sum(r[1] for r in rows),
        "by_source": {r[0]: r[1] for r in rows},
        "by_section": {r[0]: r[1] for r in rows},
        "properties_with_files": db.query(func.count(func.distinct(PropertyFile.property_id))).filter(
            PropertyFile.org_id == user.org_id
        ).scalar() or 0,
    }


@router.post("/link")
async def link_file(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually link a file to a property."""
    body = await request.json()
    f = PropertyFile(
        org_id=user.org_id,
        property_id=body["property_id"],
        kind=body.get("kind", "DOCUMENT"),
        name=body.get("name", ""),
        path=body.get("path", ""),
        source=body.get("source", "manual"),
        section=body.get("section", ""),
        obsidian_vault=body.get("obsidian_vault", ""),
        size_bytes=body.get("size_bytes", 0),
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return {"id": f.id, "ok": True}