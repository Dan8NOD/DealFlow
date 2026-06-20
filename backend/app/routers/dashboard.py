"""Dashboard routes - the main portal view."""
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app.db import get_db
from app.auth import get_current_user
from app.models import (
    User, Property, Lead, Application, ApplicationEvent,
    SalesDeal, CmaRequest, PropertyFile, Organization,
)

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = user.organization
    org_id = org.id
    # Pipeline counts
    in_pipeline = db.query(Application).filter(
        Application.org_id == org_id,
        Application.status.in_(["application_received", "offer_sent", "approved"])
    ).count()
    active_sales = db.query(SalesDeal).filter(
        SalesDeal.org_id == org_id,
        SalesDeal.status.in_(["under_contract", "active_listing", "in_escrow", "contract_signed", "offer_received"])
    ).count()
    pending_cmas = db.query(CmaRequest).filter(
        CmaRequest.org_id == org_id,
        CmaRequest.status == "pending"
    ).count()
    active_leads = db.query(Lead).filter(
        Lead.org_id == org_id,
        Lead.status.in_(["new", "contacted", "qualified"])
    ).count()
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    new_apps_7d = db.query(Application).filter(
        Application.org_id == org_id,
        Application.created_at >= week_ago
    ).count()
    # Top pending (apps in pipeline)
    pending_apps = db.query(Application).filter(
        Application.org_id == org_id,
        Application.status.in_(["application_received", "offer_sent", "welcome_sent", "approved"])
    ).order_by(desc(Application.days_in_pipeline)).limit(50).all()
    # Active sales
    active_deals = db.query(SalesDeal).filter(
        SalesDeal.org_id == org_id,
        SalesDeal.status != "closed"
    ).order_by(desc(SalesDeal.last_update)).limit(20).all()
    # Pending CMAs
    cmas = db.query(CmaRequest).filter(
        CmaRequest.org_id == org_id,
        CmaRequest.status == "pending"
    ).order_by(desc(CmaRequest.last_request)).limit(20).all()
    # Recent leads
    recent_leads = db.query(Lead).filter(
        Lead.org_id == org_id,
    ).order_by(desc(Lead.received_at)).limit(20).all()
    # Top properties by lead count
    top_properties = db.query(
        Property.address, Property.unit, func.count(Lead.id).label('lead_count')
    ).outerjoin(Lead, Lead.property_id == Property.id).filter(
        Property.org_id == org_id
    ).group_by(Property.id).order_by(desc('lead_count')).limit(10).all()
    # Application status distribution
    status_dist = db.query(
        Application.status, func.count(Application.id).label('cnt')
    ).filter(Application.org_id == org_id).group_by(Application.status).all()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "org": org,
        "now": datetime.now(),
        "stats": {
            "active_leads": active_leads,
            "in_pipeline": in_pipeline,
            "active_sales": active_sales,
            "pending_cmas": pending_cmas,
            "new_apps_7d": new_apps_7d,
        },
        "pending_apps": pending_apps,
        "active_deals": active_deals,
        "cmas": cmas,
        "recent_leads": recent_leads,
        "top_properties": top_properties,
        "status_dist": status_dist,
    })


@router.get("/api/dashboard.json")
async def dashboard_json(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org_id = user.org_id
    return {
        "stats": {
            "active_leads": db.query(Lead).filter(
                Lead.org_id == org_id,
                Lead.status.in_(["new", "contacted"])
            ).count(),
            "in_pipeline": db.query(Application).filter(
                Application.org_id == org_id,
                Application.status.in_(["application_received", "offer_sent", "approved"])
            ).count(),
            "active_sales": db.query(SalesDeal).filter(
                SalesDeal.org_id == org_id,
                SalesDeal.status != "closed"
            ).count(),
            "pending_cmas": db.query(CmaRequest).filter(
                CmaRequest.org_id == org_id, CmaRequest.status == "pending"
            ).count(),
        },
        "applications": [
            {
                "id": a.id, "property": a.property.address if a.property else "",
                "unit": a.unit, "applicant": a.applicant_name,
                "status": a.status.value if a.status else "",
                "handler": a.handler,
                "days": a.days_in_pipeline or 0,
                "updated": a.last_update.isoformat() if a.last_update else None,
                "needs_review": bool(a.needs_review),
            }
            for a in db.query(Application).filter(Application.org_id == org_id)
              .order_by(desc(Application.last_update)).limit(100).all()
        ],
        "sales": [
            {
                "id": s.id, "address": s.property_address,
                "status": s.status.value if s.status else "",
                "days_idle": s.days_idle or 0,
                "tc": s.transaction_coordinator,
                "updated": s.last_update.isoformat() if s.last_update else None,
            }
            for s in db.query(SalesDeal).filter(SalesDeal.org_id == org_id)
              .order_by(desc(SalesDeal.last_update)).limit(100).all()
        ],
        "cmas": [
            {
                "id": c.id, "property": c.property_address, "unit": c.unit,
                "kind": c.kind, "status": c.status,
                "requests": c.request_count,
                "first": c.first_request.isoformat() if c.first_request else None,
                "last": c.last_request.isoformat() if c.last_request else None,
            }
            for c in db.query(CmaRequest).filter(CmaRequest.org_id == org_id)
              .order_by(desc(CmaRequest.last_request)).limit(100).all()
        ],
        "leads": [
            {
                "id": l.id, "name": l.name, "email": l.email, "phone": l.phone,
                "property": (l.property.address if l.property else "") + (f" #{l.property.unit}" if l.property and l.property.unit else ""),
                "source": l.source,
                "status": l.status.value if l.status else "",
                "days_old": l.days_old or 0,
            }
            for l in db.query(Lead).filter(Lead.org_id == org_id)
              .order_by(desc(Lead.received_at)).limit(100).all()
        ],
    }


@router.get("/api/applications")
async def api_applications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str = Query(None),
    limit: int = Query(200, le=500),
):
    q = db.query(Application).filter(Application.org_id == user.org_id)
    if status:
        q = q.filter(Application.status == status)
    apps = q.order_by(desc(Application.last_update)).limit(limit).all()
    return [
        {
            "id": a.id,
            "property": (a.property.address if a.property else "") + (f" #{a.property.unit}" if a.property and a.property.unit else ""),
            "applicant": a.applicant_name,
            "status": a.status.value if a.status else "",
            "handler": a.handler,
            "days_in_pipeline": a.days_in_pipeline or 0,
            "event_count": a.event_count or 0,
            "needs_review": bool(a.needs_review),
            "last_update": a.last_update.isoformat() if a.last_update else None,
        }
        for a in apps
    ]


@router.get("/api/sales")
async def api_sales(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str = Query(None),
):
    q = db.query(SalesDeal).filter(SalesDeal.org_id == user.org_id)
    if status:
        q = q.filter(SalesDeal.status == status)
    deals = q.order_by(desc(SalesDeal.last_update)).all()
    return [
        {
            "id": d.id, "address": d.property_address,
            "status": d.status.value if d.status else "",
            "tc": d.transaction_coordinator,
            "days_idle": d.days_idle or 0,
            "event_count": d.event_count or 0,
            "last_update": d.last_update.isoformat() if d.last_update else None,
        }
        for d in deals
    ]


@router.get("/api/cmas")
async def api_cmas(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str = Query(None),
):
    q = db.query(CmaRequest).filter(CmaRequest.org_id == user.org_id)
    if status:
        q = q.filter(CmaRequest.status == status)
    cmas = q.order_by(desc(CmaRequest.last_request)).all()
    return [
        {
            "id": c.id, "property": c.property_address, "unit": c.unit,
            "kind": c.kind, "status": c.status, "requests": c.request_count,
            "first_request": c.first_request.isoformat() if c.first_request else None,
            "last_request": c.last_request.isoformat() if c.last_request else None,
        }
        for c in cmas
    ]


@router.get("/api/leads")
async def api_leads(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str = Query(None),
    limit: int = Query(200, le=500),
):
    q = db.query(Lead).filter(Lead.org_id == user.org_id)
    if status:
        q = q.filter(Lead.status == status)
    leads = q.order_by(desc(Lead.received_at)).limit(limit).all()
    return [
        {
            "id": l.id, "name": l.name, "email": l.email, "phone": l.phone,
            "property": (l.property.address if l.property else "") + (f" #{l.property.unit}" if l.property and l.property.unit else ""),
            "source": l.source,
            "status": l.status.value if l.status else "",
            "days_old": l.days_old or 0,
            "received_at": l.received_at.isoformat() if l.received_at else None,
        }
        for l in leads
    ]


@router.get("/api/properties")
async def api_properties(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    props = db.query(Property).filter(Property.org_id == user.org_id).all()
    return [
        {
            "id": p.id, "address": p.address, "unit": p.unit,
            "status": p.status.value if p.status else "",
            "rent": p.rent, "bedrooms": p.bedrooms, "bathrooms": p.bathrooms,
            "tenant": p.tenant_name,
        }
        for p in props
    ]


@router.get("/api/applications/{app_id}/events")
async def api_application_events(
    app_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.query(Application).filter(
        Application.id == app_id,
        Application.org_id == user.org_id,
    ).first()
    if not app:
        return JSONResponse({"error": "not found"}, status_code=404)
    events = db.query(ApplicationEvent).filter(
        ApplicationEvent.application_id == app_id
    ).order_by(ApplicationEvent.occurred_at).all()
    return [
        {
            "id": e.id,
            "type": e.event_type,
            "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
            "handler": e.handler,
            "subject": e.subject,
        }
        for e in events
    ]


@router.get("/api/sync")
async def api_sync(
    user: User = Depends(get_current_user),
):
    """Trigger email sync for the current org (all connected accounts)."""
    from app.integrations.sync_engine import sync_org
    result = await sync_org(user.org_id)
    return result


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})
