"""
Tenant portal — public-facing pages for tenants (maintenance requests, payments, docs).
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from pathlib import Path

from app.db import Base, get_db
from app.auth import get_current_user
from app.models import User, Property

router = APIRouter(tags=["tenant"])


class MaintenanceRequest(Base):
    __tablename__ = "maintenance_requests"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), index=True)
    tenant_name = Column(String(200))
    tenant_email = Column(String(200))
    tenant_phone = Column(String(50))
    subject = Column(String(300), nullable=False)
    description = Column(Text)
    urgency = Column(String(20), default="normal")  # low, normal, urgent, emergency
    status = Column(String(20), default="submitted")  # submitted, acknowledged, in_progress, resolved, closed
    category = Column(String(50))  # plumbing, electrical, hvac, appliance, structural, pest, other
    resolved_at = Column(DateTime)
    notes = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


# ── Tenant-facing portal page (no auth required) ─────────────────────────────

@router.get("/tenant/{property_token}", response_class=HTMLResponse)
async def tenant_portal(request: Request, property_token: str, db: Session = Depends(get_db)):
    """Public tenant portal — accessible via unique token link."""
    # For now, token = property id (in production, use a hash)
    try:
        prop_id = int(property_token)
    except ValueError:
        return HTMLResponse("<h1>Invalid link</h1>", status_code=404)

    prop = db.query(Property).filter(Property.id == prop_id).first()
    if not prop:
        return HTMLResponse("<h1>Property not found</h1>", status_code=404)

    return templates.TemplateResponse("tenant.html", {
        "request": request,
        "property": {
            "id": prop.id,
            "address": prop.address,
            "unit": prop.unit,
            "city": prop.city,
            "state": prop.state,
            "tenant_name": prop.tenant_name,
        },
        "token": property_token,
    })


# ── API: maintenance requests ────────────────────────────────────────────────

@router.get("/api/maintenance")
async def list_maintenance(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    property_id: int = Query(None),
    status: str = Query(None),
    limit: int = Query(50, le=200),
):
    q = db.query(MaintenanceRequest).filter(MaintenanceRequest.org_id == user.org_id)
    if property_id:
        q = q.filter(MaintenanceRequest.property_id == property_id)
    if status:
        q = q.filter(MaintenanceRequest.status == status)
    q = q.order_by(MaintenanceRequest.created_at.desc()).limit(limit)

    # Get property addresses
    prop_ids = {m.property_id for m in q.all()}
    props = {p.id: p for p in db.query(Property).filter(Property.id.in_(prop_ids)).all()}

    return [{
        "id": m.id, "property_id": m.property_id,
        "property_address": f"{props[m.property_id].address} #{props[m.property_id].unit}" if m.property_id in props and props[m.property_id].unit else (props[m.property_id].address if m.property_id in props else ""),
        "tenant_name": m.tenant_name, "tenant_email": m.tenant_email,
        "tenant_phone": m.tenant_phone,
        "subject": m.subject, "description": m.description,
        "urgency": m.urgency, "status": m.status, "category": m.category,
        "notes": m.notes,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "resolved_at": m.resolved_at.isoformat() if m.resolved_at else None,
    } for m in q.all()]


@router.post("/api/maintenance")
async def create_maintenance(
    request: Request,
    db: Session = Depends(get_db),
):
    """Public endpoint — tenants submit maintenance requests."""
    body = await request.json()
    prop_id = body.get("property_id")

    # Find org_id from property
    prop = db.query(Property).filter(Property.id == prop_id).first()
    if not prop:
        return JSONResponse({"error": "property not found"}, status_code=404)

    m = MaintenanceRequest(
        org_id=prop.org_id,
        property_id=prop_id,
        tenant_name=body.get("tenant_name", ""),
        tenant_email=body.get("tenant_email", ""),
        tenant_phone=body.get("tenant_phone", ""),
        subject=body.get("subject", ""),
        description=body.get("description", ""),
        urgency=body.get("urgency", "normal"),
        category=body.get("category", "other"),
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return {"id": m.id, "ok": True, "message": "Maintenance request submitted"}


@router.patch("/api/maintenance/{req_id}")
async def update_maintenance(
    req_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    m = db.query(MaintenanceRequest).filter(
        MaintenanceRequest.id == req_id,
        MaintenanceRequest.org_id == user.org_id,
    ).first()
    if not m:
        return JSONResponse({"error": "not found"}, status_code=404)

    for field in ("status", "urgency", "category", "notes", "resolved_at"):
        if field in body:
            setattr(m, field, body[field])
    if body.get("status") == "resolved" and not m.resolved_at:
        m.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "id": req_id}


@router.get("/api/maintenance/stats")
async def maintenance_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import func as F
    return {
        "open": db.query(MaintenanceRequest).filter(
            MaintenanceRequest.org_id == user.org_id,
            MaintenanceRequest.status.in_(["submitted", "acknowledged", "in_progress"])
        ).count(),
        "resolved": db.query(MaintenanceRequest).filter(
            MaintenanceRequest.org_id == user.org_id,
            MaintenanceRequest.status == "resolved"
        ).count(),
        "urgent": db.query(MaintenanceRequest).filter(
            MaintenanceRequest.org_id == user.org_id,
            MaintenanceRequest.urgency.in_(["urgent", "emergency"]),
            MaintenanceRequest.status != "resolved"
        ).count(),
        "by_category": [
            {"category": row[0], "count": row[1]}
            for row in db.query(
                MaintenanceRequest.category,
                F.count(MaintenanceRequest.id)
            ).filter(
                MaintenanceRequest.org_id == user.org_id
            ).group_by(MaintenanceRequest.category).all()
        ],
    }