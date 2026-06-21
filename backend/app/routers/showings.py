"""
Showing scheduler — ShowMojo-style showing coordination.
Models and router for scheduling, tracking, and managing property showings.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.sql import func

from app.db import Base, get_db
from app.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/api/showings", tags=["showings"])


class Showing(Base):
    __tablename__ = "showings"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), index=True)
    prospect_name = Column(String(200))
    prospect_email = Column(String(200))
    prospect_phone = Column(String(50))
    scheduled_at = Column(DateTime, nullable=False, index=True)
    end_at = Column(DateTime)
    status = Column(String(20), default="scheduled")  # scheduled, confirmed, completed, cancelled, no_show
    method = Column(String(20), default="in_person")  # in_person, virtual, open_house
    agent = Column(String(200))
    lockbox_code = Column(String(20))
    notes = Column(Text)
    feedback = Column(Text)
    showmojo_id = Column(String(100))
    created_at = Column(DateTime, server_default=func.now())


# ── API ──────────────────────────────────────────────────────────────────────

@router.get("")
async def list_showings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str = Query(None),
    property_id: int = Query(None),
    limit: int = Query(100, le=300),
):
    q = db.query(Showing).filter(Showing.org_id == user.org_id)
    if status:
        q = q.filter(Showing.status == status)
    if property_id:
        q = q.filter(Showing.property_id == property_id)
    q = q.order_by(Showing.scheduled_at).limit(limit)

    return [{
        "id": s.id, "property_id": s.property_id,
        "prospect_name": s.prospect_name, "prospect_email": s.prospect_email,
        "prospect_phone": s.prospect_phone,
        "scheduled_at": s.scheduled_at.isoformat() if s.scheduled_at else None,
        "end_at": s.end_at.isoformat() if s.end_at else None,
        "status": s.status, "method": s.method, "agent": s.agent,
        "lockbox_code": s.lockbox_code, "notes": s.notes, "feedback": s.feedback,
        "showmojo_id": s.showmojo_id,
    } for s in q.all()]


@router.get("/upcoming")
async def upcoming_showings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, le=100),
):
    """Get next N upcoming showings across all properties."""
    now = datetime.now(timezone.utc)
    showings = db.query(Showing).filter(
        Showing.org_id == user.org_id,
        Showing.scheduled_at >= now,
        Showing.status.in_(["scheduled", "confirmed"]),
    ).order_by(Showing.scheduled_at).limit(limit).all()

    # Get property addresses
    from app.models import Property
    prop_ids = {s.property_id for s in showings}
    props = {p.id: p for p in db.query(Property).filter(Property.id.in_(prop_ids)).all()}

    return [{
        "id": s.id, "property_id": s.property_id,
        "property_address": f"{props[s.property_id].address} #{props[s.property_id].unit}" if s.property_id in props and props[s.property_id].unit else (props[s.property_id].address if s.property_id in props else ""),
        "prospect_name": s.prospect_name, "prospect_phone": s.prospect_phone,
        "prospect_email": s.prospect_email,
        "scheduled_at": s.scheduled_at.isoformat() if s.scheduled_at else None,
        "end_at": s.end_at.isoformat() if s.end_at else None,
        "status": s.status, "method": s.method, "agent": s.agent,
        "notes": s.notes,
    } for s in showings]


@router.post("")
async def create_showing(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    s = Showing(
        org_id=user.org_id,
        property_id=body.get("property_id"),
        prospect_name=body.get("prospect_name", ""),
        prospect_email=body.get("prospect_email", ""),
        prospect_phone=body.get("prospect_phone", ""),
        scheduled_at=body.get("scheduled_at"),
        end_at=body.get("end_at"),
        status=body.get("status", "scheduled"),
        method=body.get("method", "in_person"),
        agent=body.get("agent", ""),
        lockbox_code=body.get("lockbox_code", ""),
        notes=body.get("notes", ""),
        showmojo_id=body.get("showmojo_id", ""),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "ok": True}


@router.patch("/{showing_id}")
async def update_showing(
    showing_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    s = db.query(Showing).filter(Showing.id == showing_id, Showing.org_id == user.org_id).first()
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    for field in ("status", "method", "agent", "prospect_name", "prospect_email",
                  "prospect_phone", "scheduled_at", "end_at", "lockbox_code",
                  "notes", "feedback", "showmojo_id"):
        if field in body:
            setattr(s, field, body[field])
    db.commit()
    return {"ok": True, "id": showing_id}


@router.get("/stats")
async def showing_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Showing pipeline stats."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    return {
        "upcoming": db.query(Showing).filter(
            Showing.org_id == user.org_id,
            Showing.scheduled_at >= now,
            Showing.status.in_(["scheduled", "confirmed"]),
        ).count(),
        "today": db.query(Showing).filter(
            Showing.org_id == user.org_id,
            Showing.scheduled_at >= today_start,
            Showing.scheduled_at < today_start + timedelta(days=1),
        ).count(),
        "this_week": db.query(Showing).filter(
            Showing.org_id == user.org_id,
            Showing.scheduled_at >= week_start,
        ).count(),
        "completed": db.query(Showing).filter(
            Showing.org_id == user.org_id,
            Showing.status == "completed",
        ).count(),
        "no_show": db.query(Showing).filter(
            Showing.org_id == user.org_id,
            Showing.status == "no_show",
        ).count(),
        "by_method": {
            "in_person": db.query(Showing).filter(
                Showing.org_id == user.org_id, Showing.method == "in_person"
            ).count(),
            "virtual": db.query(Showing).filter(
                Showing.org_id == user.org_id, Showing.method == "virtual"
            ).count(),
            "open_house": db.query(Showing).filter(
                Showing.org_id == user.org_id, Showing.method == "open_house"
            ).count(),
        },
    }