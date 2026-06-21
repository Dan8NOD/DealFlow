"""Dashboard routes - the main portal view with inline editing & comments."""
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
    SalesDeal, CmaRequest, PropertyFile, Organization, Comment,
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
    in_pipeline = db.query(Application).filter(
        Application.org_id == org_id,
        Application.status.in_(["APPLICATION_RECEIVED", "OFFER_SENT", "APPROVED"])
    ).count()
    active_sales = db.query(SalesDeal).filter(
        SalesDeal.org_id == org_id,
        SalesDeal.status.in_(["UNDER_CONTRACT", "ACTIVE_LISTING", "IN_ESCROW", "CONTRACT_SIGNED", "OFFER_RECEIVED"])
    ).count()
    pending_cmas = db.query(CmaRequest).filter(
        CmaRequest.org_id == org_id,
        CmaRequest.status == "pending"
    ).count()
    active_leads = db.query(Lead).filter(
        Lead.org_id == org_id,
        Lead.status.in_(["NEW", "CONTACTED", "QUALIFIED"])
    ).count()
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    new_apps_7d = db.query(Application).filter(
        Application.org_id == org_id,
        Application.created_at >= week_ago
    ).count()
    pending_apps = db.query(Application).filter(
        Application.org_id == org_id,
        Application.status.in_(["APPLICATION_RECEIVED", "OFFER_SENT", "WELCOME_SENT", "APPROVED"])
    ).order_by(desc(Application.days_in_pipeline)).limit(50).all()
    active_deals = db.query(SalesDeal).filter(
        SalesDeal.org_id == org_id,
        SalesDeal.status != "CLOSED"
    ).order_by(desc(SalesDeal.last_update)).limit(20).all()
    cmas = db.query(CmaRequest).filter(
        CmaRequest.org_id == org_id,
        CmaRequest.status == "pending"
    ).order_by(desc(CmaRequest.last_request)).limit(20).all()
    recent_leads = db.query(Lead).filter(
        Lead.org_id == org_id,
    ).order_by(desc(Lead.received_at)).limit(20).all()
    top_properties = db.query(
        Property.address, Property.unit, func.count(Lead.id).label('lead_count')
    ).outerjoin(Lead, Lead.property_id == Property.id).filter(
        Property.org_id == org_id
    ).group_by(Property.id).order_by(desc('lead_count')).limit(10).all()
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


@router.get("/api/debug-dashboard")
async def debug_dashboard(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Debug: test each query individually to find which crashes."""
    import traceback
    org_id = user.org_id
    results = {}
    tests = [
        ("in_pipeline", lambda: db.query(Application).filter(Application.org_id == org_id, Application.status.in_(["APPLICATION_RECEIVED", "OFFER_SENT", "APPROVED"])).count()),
        ("active_sales", lambda: db.query(SalesDeal).filter(SalesDeal.org_id == org_id, SalesDeal.status.in_(["UNDER_CONTRACT", "ACTIVE_LISTING", "IN_ESCROW", "CONTRACT_SIGNED", "OFFER_RECEIVED"])).count()),
        ("pending_cmas", lambda: db.query(CmaRequest).filter(CmaRequest.org_id == org_id, CmaRequest.status == "pending").count()),
        ("active_leads", lambda: db.query(Lead).filter(Lead.org_id == org_id, Lead.status.in_(["NEW", "CONTACTED", "QUALIFIED"])).count()),
        ("new_apps_7d", lambda: db.query(Application).filter(Application.org_id == org_id, Application.created_at >= datetime.now(timezone.utc) - timedelta(days=7)).count()),
        ("pending_apps_query", lambda: db.query(Application).filter(Application.org_id == org_id, Application.status.in_(["APPLICATION_RECEIVED", "OFFER_SENT", "WELCOME_SENT", "APPROVED"])).order_by(desc(Application.days_in_pipeline)).limit(50).all()),
        ("status_dist", lambda: db.query(Application.status, func.count(Application.id).label('cnt')).filter(Application.org_id == org_id).group_by(Application.status).all()),
        ("all_apps_no_filter", lambda: db.query(Application).filter(Application.org_id == org_id).order_by(desc(Application.last_update)).limit(5).all()),
        ("all_apps_count", lambda: db.query(Application).filter(Application.org_id == org_id).count()),
    ]
    for name, fn in tests:
        try:
            val = fn()
            results[name] = str(type(val).__name__)
        except Exception as e:
            results[name] = f"CRASH: {type(e).__name__}: {str(e)[:200]}"
    return results


@router.post("/api/enrich-leads")
async def enrich_leads(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    One-shot: enrich all matched leads with estimated budget (property rent × 3).
    Also backfills property_id for leads with a property address string.
    """
    org_id = user.org_id
    enriched = 0
    backfilled = 0

    # Build property lookup by address key
    props = db.query(Property).filter(Property.org_id == org_id).all()
    import re
    def extract_key(addr):
        if not addr:
            return ""
        a = addr.lower().strip()
        a = re.sub(r'\.', '', a)
        a = re.sub(r'\b(street|st|avenue|ave|boulevard|blvd|road|rd|drive|dr)\b', '', a)
        a = re.sub(r'\b(south|north|east|west)\b', '', a)
        a = re.sub(r'[,;:]', '', a)
        a = re.sub(r'\s*(?:-)\s*[a-z0-9]+\s*$', '', a)
        a = re.sub(r'\s+', ' ', a).strip()
        m = re.match(r'(\d+)\s+(\w+)', a)
        return f"{m.group(1)} {m.group(2)}" if m else a[:30]

    pidx = {}
    for p in props:
        k = extract_key(p.address)
        if k:
            pidx[k] = p

    # 1. Backfill property_id for leads without one
    orphan_leads = db.query(Lead).filter(
        Lead.org_id == org_id,
        Lead.property_id.is_(None),
        Lead.subject.isnot(None),
        Lead.subject != "",
    ).all()

    for lead in orphan_leads:
        # Try to extract property address from subject
        key = extract_key(lead.subject or "")
        if key in pidx:
            lead.property_id = pidx[key].id
            backfilled += 1

    # 2. Enrich leads with budget from property rent
    matched_leads = db.query(Lead).filter(
        Lead.org_id == org_id,
        Lead.property_id.isnot(None),
        Lead.monthly_income.is_(None),
    ).all()

    for lead in matched_leads:
        prop = db.query(Property).filter(Property.id == lead.property_id).first()
        if prop and prop.rent and prop.rent > 0:
            budget = int(prop.rent * 3)  # 3x rent qualification
            lead.monthly_income = float(budget)
            lead.income_source = "estimated_from_rent"
            if not lead.notes:
                lead.notes = f"Budget: ${budget}/mo (3x ${int(prop.rent)} rent at {prop.address})"
            enriched += 1

    db.commit()
    return {"backfilled": backfilled, "enriched": enriched, "total_leads": db.query(Lead).filter(Lead.org_id == org_id).count()}


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
                Lead.status.in_(["NEW", "CONTACTED"])
            ).count(),
            "in_pipeline": db.query(Application).filter(
                Application.org_id == org_id,
                Application.status.in_(["APPLICATION_RECEIVED", "OFFER_SENT", "APPROVED"])
            ).count(),
            "active_sales": db.query(SalesDeal).filter(
                SalesDeal.org_id == org_id,
                SalesDeal.status != "CLOSED"
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
            "property_id": a.property_id,
            "property": (a.property.address if a.property else "") + (f" #{a.property.unit}" if a.property and a.property.unit else ""),
            "applicant": a.applicant_name,
            "status": a.status.value if a.status else "",
            "handler": a.handler,
            "unit": a.unit,
            "days_in_pipeline": a.days_in_pipeline or 0,
            "event_count": a.event_count or 0,
            "needs_review": bool(a.needs_review),
            "first_seen": a.first_seen.isoformat() if a.first_seen else None,
            "last_update": a.last_update.isoformat() if a.last_update else None,
            "monthly_income": a.monthly_income,
            "credit_score": a.credit_score,
            "pets": a.pets,
            "move_in_date": a.move_in_date,
            "notes": a.notes,
        }
        for a in apps
    ]


@router.get("/api/sales")
async def api_sales(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    q = db.query(SalesDeal).filter(SalesDeal.org_id == user.org_id)
    if status:
        q = q.filter(SalesDeal.status == status)
    deals = q.order_by(desc(SalesDeal.last_update)).offset(offset).limit(limit).all()
    return [
        {
            "id": d.id, "address": d.property_address,
            "status": d.status.value if d.status else "",
            "tc": d.transaction_coordinator,
            "list_price": d.list_price,
            "days_idle": d.days_idle or 0,
            "event_count": d.event_count or 0,
            "last_update": d.last_update.isoformat() if d.last_update else None,
            "first_seen": d.first_seen.isoformat() if d.first_seen else None,
        }
        for d in deals
    ]


@router.get("/api/cmas")
async def api_cmas(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    q = db.query(CmaRequest).filter(CmaRequest.org_id == user.org_id)
    if status:
        q = q.filter(CmaRequest.status == status)
    cmas = q.order_by(desc(CmaRequest.last_request)).offset(offset).limit(limit).all()
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
    property_id: int = Query(None),
    limit: int = Query(200, le=500),
):
    q = db.query(Lead).filter(Lead.org_id == user.org_id)
    if status:
        q = q.filter(Lead.status == status)
    if property_id:
        q = q.filter(Lead.property_id == property_id)
    leads = q.order_by(desc(Lead.received_at)).limit(limit).all()
    return [
        {
            "id": l.id, "name": l.name, "email": l.email, "phone": l.phone,
            "property": (l.property.address if l.property else "") + (f" #{l.property.unit}" if l.property and l.property.unit else ""),
            "property_id": l.property_id,
            "source": l.source,
            "status": l.status.value if l.status else "",
            "days_old": l.days_old or 0,
            "received_at": l.received_at.isoformat() if l.received_at else None,
            "monthly_income": l.monthly_income,
            "income_source": l.income_source,
            "upsell_eligible": bool(l.upsell_eligible),
            "interested_in_buying": bool(l.interested_in_buying),
            "notes": l.notes,
            # New call-tracking fields
            "move_in_date": l.move_in_date,
            "last_called": l.last_called.isoformat() if l.last_called is not None else None,
            "call_outcome": l.call_outcome,
            "call_notes": l.call_notes,
            "bounce_to": l.bounce_to,
        }
        for l in leads
    ]


@router.get("/api/properties")
async def api_properties(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort: str = Query("address", regex="^(address|rent|bedrooms|status|available_date)$"),
    enriched: bool = Query(False, description="Only return properties with Obsidian enrichment"),
):
    q = db.query(Property).filter(Property.org_id == user.org_id)
    if status:
        q = q.filter(Property.status == status)
    if enriched:
        q = q.filter(
            (Property.pet_restrictions.isnot(None)) |
            (Property.mls_id.isnot(None)) |
            (Property.lockbox_code.isnot(None))
        )
    sort_map = {
        "address": Property.address,
        "rent": Property.rent,
        "bedrooms": Property.bedrooms,
        "status": Property.status,
        "available_date": Property.available_date,
    }
    q = q.order_by(sort_map.get(sort, Property.address))
    props = q.offset(offset).limit(limit).all()
    return [
        {
            "id": p.id, "address": p.address, "unit": p.unit,
            "status": p.status.value if p.status else "",
            "rent": p.rent, "bedrooms": p.bedrooms, "bathrooms": p.bathrooms,
            "square_feet": p.square_feet,
            "tenant": p.tenant_name, "notes": p.notes,
            "city": p.city, "state": p.state, "zip_code": p.zip_code,
            # New fields from Obsidian enrichment
            "pet_restrictions": p.pet_restrictions,
            "utilities_included": p.utilities_included,
            "utilities_paid_by_tenant": p.utilities_paid_by_tenant,
            "parking": p.parking,
            "storage": p.storage,
            "laundry": p.laundry,
            "asset_manager": p.asset_manager,
            "lockbox_code": p.lockbox_code,
            "listing_description": p.listing_description,
            "mls_id": p.mls_id,
            "cma_link": p.cma_link,
            "showing_instructions": p.showing_instructions,
        }
        for p in props
    ]


@router.get("/api/properties/showing-sheet")
async def showing_sheet(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str = Query(None, description="Filter: AVAILABLE, RENTED, etc."),
    has_lockbox: bool = Query(False, description="Only properties with lockbox codes"),
    min_bedrooms: int = Query(None, ge=0),
    max_rent: float = Query(None, ge=0),
    sort: str = Query("status_priority", regex="^(status_priority|rent|bedrooms|address)$"),
):
    """
    Compact showing-sheet endpoint — returns only the fields you need
    when showing apartments on your phone. Sorted by status priority
    (AVAILABLE first, OCCUPIED last) then by address.
    """
    q = db.query(Property).filter(Property.org_id == user.org_id)
    if status:
        q = q.filter(Property.status == status)
    if has_lockbox:
        q = q.filter(Property.lockbox_code.isnot(None))
    if min_bedrooms:
        q = q.filter(Property.bedrooms >= min_bedrooms)
    if max_rent:
        q = q.filter(Property.rent <= max_rent)

    props = q.all()

    # Status priority for sorting
    status_order = {
        "AVAILABLE": 0, "Available": 0, "FOR_SALE": 1,
        "OCCUPIED": 2, "RENTED": 2, "Rented": 2,
        "OFF_MARKET": 3, "PENDING": 3,
    }

    def sort_key(p):
        s = status_order.get(p.status, 99)
        return (s, p.address or "", p.unit or "")

    props.sort(key=sort_key)

    return [
        {
            "id": p.id,
            "address": p.address,
            "unit": p.unit,
            "city": p.city,
            "bedrooms": p.bedrooms,
            "bathrooms": p.bathrooms,
            "rent": p.rent,
            "status": p.status.value if p.status else "",
            # Showing-critical fields
            "lockbox_code": p.lockbox_code,
            "showing_instructions": p.showing_instructions,
            "pet_restrictions": p.pet_restrictions,
            "parking": p.parking,
            "utilities_paid_by_tenant": p.utilities_paid_by_tenant,
            "utilities_included": p.utilities_included,
            "tenant_name": p.tenant_name,
            "available_date": p.available_date.isoformat() if p.available_date is not None else None,
            # Quick reference
            "mls_id": p.mls_id,
            "asset_manager": p.asset_manager,
            "cma_link": p.cma_link,
            "listing_description": (str(p.listing_description)[:200] + "...") if str(p.listing_description or "").strip() and len(str(p.listing_description or "")) > 200 else str(p.listing_description or "")[:500] if str(p.listing_description or "").strip() else None,
            # Lead activity summary
            "lead_count": db.query(Lead).filter(
                Lead.property_id == p.id,
                Lead.org_id == user.org_id
            ).count(),
            "active_apps": db.query(Application).filter(
                Application.property_id == p.id,
                Application.org_id == user.org_id,
                Application.status.in_(["APPLICATION_RECEIVED", "OFFER_SENT", "APPROVED"])
            ).count(),
        }
        for p in props
    ]


@router.get("/showing", response_class=HTMLResponse)
async def showing_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mobile-optimized showing sheet — view on phone while at apartments."""
    return templates.TemplateResponse("showing.html", {
        "request": request,
        "user": user,
    })
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


# ═══════════ PATCH endpoints (Airtable-style inline editing) ═══════════

@router.patch("/api/applications/{app_id}")
async def patch_application(
    app_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    app = db.query(Application).filter(Application.id == app_id, Application.org_id == user.org_id).first()
    if not app:
        return JSONResponse({"error": "not found"}, status_code=404)
    for field in ("status", "handler", "applicant_name", "monthly_income", "credit_score", "pets", "move_in_date", "notes"):
        if field in body:
            setattr(app, field, body[field])
    if "last_update" not in body:
        app.last_update = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "id": app_id}


@router.patch("/api/leads/{lead_id}")
async def patch_lead(
    lead_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.org_id == user.org_id).first()
    if not lead:
        return JSONResponse({"error": "not found"}, status_code=404)
    for field in ("status", "name", "email", "phone", "monthly_income", "income_source",
                   "interested_in_buying", "notes", "move_in_date", "call_outcome",
                   "call_notes", "bounce_to"):
        if field in body:
            setattr(lead, field, body[field])
    # Auto-calculate upsell eligibility: income > $5k/mo → flag
    income = getattr(lead, 'monthly_income', None)
    if income is not None and income > 0:
        lead.upsell_eligible = income >= 5000
    db.commit()
    return {"ok": True, "id": lead_id}


@router.patch("/api/sales/{deal_id}")
async def patch_sales(
    deal_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    deal = db.query(SalesDeal).filter(SalesDeal.id == deal_id, SalesDeal.org_id == user.org_id).first()
    if not deal:
        return JSONResponse({"error": "not found"}, status_code=404)
    for field in ("status", "transaction_coordinator", "list_price"):
        if field in body:
            setattr(deal, field, body[field])
    if "last_update" not in body:
        deal.last_update = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "id": deal_id}


@router.patch("/api/properties/{prop_id}")
async def patch_property(
    prop_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    prop = db.query(Property).filter(Property.id == prop_id, Property.org_id == user.org_id).first()
    if not prop:
        return JSONResponse({"error": "not found"}, status_code=404)
    for field in ("status", "tenant_name", "rent", "notes", "bedrooms", "bathrooms",
                   "pet_restrictions", "utilities_included", "utilities_paid_by_tenant",
                   "parking", "storage", "laundry", "asset_manager", "lockbox_code",
                   "listing_description", "mls_id", "cma_link", "showing_instructions"):
        if field in body:
            setattr(prop, field, body[field])
    db.commit()
    return {"ok": True, "id": prop_id}


@router.patch("/api/cmas/{cma_id}")
async def patch_cma(
    cma_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    cma = db.query(CmaRequest).filter(CmaRequest.id == cma_id, CmaRequest.org_id == user.org_id).first()
    if not cma:
        return JSONResponse({"error": "not found"}, status_code=404)
    if "status" in body:
        cma.status = body["status"]
    db.commit()
    return {"ok": True, "id": cma_id}


# ═══════════ Create new records ═══════════

@router.post("/api/applications")
async def create_application(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    a = Application(
        org_id=user.org_id,
        applicant_name=body.get("applicant_name", ""),
        status=body.get("status", "APPLICATION_RECEIVED"),
        handler=body.get("handler", ""),
        property_id=body.get("property_id"),
        unit=body.get("unit", ""),
        first_seen=datetime.now(timezone.utc),
        last_update=datetime.now(timezone.utc),
        days_in_pipeline=0,
        event_count=0,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"id": a.id, "ok": True}


@router.post("/api/leads")
async def create_lead(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    l = Lead(
        org_id=user.org_id,
        name=body.get("name", ""),
        email=body.get("email", ""),
        phone=body.get("phone", ""),
        source=body.get("source", "manual"),
        status=body.get("status", "NEW"),
        property_id=body.get("property_id"),
        received_at=datetime.now(timezone.utc),
        days_old=0,
    )
    db.add(l)
    db.commit()
    db.refresh(l)
    return {"id": l.id, "ok": True}


@router.post("/api/sales")
async def create_sales_deal(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    s = SalesDeal(
        org_id=user.org_id,
        property_address=body.get("property_address", ""),
        status=body.get("status", "ACTIVE_LISTING"),
        transaction_coordinator=body.get("transaction_coordinator", ""),
        list_price=body.get("list_price"),
        first_seen=datetime.now(timezone.utc),
        last_update=datetime.now(timezone.utc),
        days_idle=0,
        event_count=0,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "ok": True}

@router.post("/api/comments")
async def create_comment(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    body = await request.json()
    record_type = body.get("record_type")
    record_id = body.get("record_id")
    content = body.get("content", "").strip()
    if not record_type or not record_id or not content:
        return JSONResponse({"error": "record_type, record_id, and content are required"}, status_code=400)
    c = Comment(
        org_id=user.org_id,
        user_id=user.id,
        record_type=record_type,
        record_id=record_id,
        content=content,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {
        "id": c.id,
        "content": c.content,
        "user_name": user.full_name or user.email,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.get("/api/comments/{record_type}/{record_id}")
async def get_comments(
    record_type: str,
    record_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comments = db.query(Comment).filter(
        Comment.org_id == user.org_id,
        Comment.record_type == record_type,
        Comment.record_id == record_id,
    ).order_by(Comment.created_at).all()
    return [
        {
            "id": c.id,
            "content": c.content,
            "user_name": c.user.full_name or c.user.email if c.user else "Unknown",
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in comments
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