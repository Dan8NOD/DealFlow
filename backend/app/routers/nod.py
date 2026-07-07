"""NOD Academy routes — students, sessions, coaching, products, Stripe."""
from fastapi import APIRouter, Depends, Request, Query, Body, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, text as sa_text
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
from app.db import get_db
from app.auth import get_current_user, require_user
from app.models import (
    User, NodStudent, NodStudentStatus, NodLevel, NodSessionType,
    NodSession, NodCoaching, Organization
)
from app.config import get_settings

router = APIRouter(tags=["nod"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


# ── Dashboard ──

@router.get("/nod", response_class=HTMLResponse)
async def nod_dashboard(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    org_id = user.org_id
    now = datetime.now(timezone.utc)

    if db.query(NodStudent).filter(NodStudent.org_id == org_id).count() == 0:
        demo = [
            NodStudent(org_id=org_id, name="Maria Garcia", email="maria@example.com", phone="312-555-0101",
                       current_level=NodLevel.LEVEL_1, sessions_completed=3, source="saturday_session"),
            NodStudent(org_id=org_id, name="James Liu", email="james@example.com", phone="312-555-0102",
                       current_level=NodLevel.LEVEL_2, sessions_completed=8, source="coaching"),
            NodStudent(org_id=org_id, name="Sarah Ahmed", email="sarah@example.com", phone="312-555-0103",
                       current_level=NodLevel.LEVEL_1, sessions_completed=1, source="referral"),
        ]
        db.add_all(demo)
        db.flush()
        db.add_all([
            NodSession(org_id=org_id, student_id=demo[0].id, session_type=NodSessionType.SATURDAY,
                       session_date=now, tools_practiced="Label, Mirror, Silence", level_focus=NodLevel.LEVEL_1,
                       duration_minutes=120, notes="Good first session. Struggled with silence."),
            NodSession(org_id=org_id, student_id=demo[1].id, session_type=NodSessionType.COACHING,
                       session_date=now, tools_practiced="Calibrated Question, Accusation Audit",
                       level_focus=NodLevel.LEVEL_2, duration_minutes=60, notes="Salary negotiation prep."),
            NodCoaching(org_id=org_id, student_id=demo[1].id, session_date=now,
                        topic="Salary negotiation prep", amount_cents=25000, paid=True),
        ])
        db.commit()

    active_students = db.query(NodStudent).filter(
        NodStudent.org_id == org_id, NodStudent.status == NodStudentStatus.ACTIVE).count()
    total_sessions = db.query(NodSession).filter(NodSession.org_id == org_id).count()
    total_coaching_revenue = db.query(func.coalesce(func.sum(NodCoaching.amount_cents), 0)).filter(
        NodCoaching.org_id == org_id, NodCoaching.paid == True).scalar()
    level_dist = db.query(NodStudent.current_level, func.count(NodStudent.id)).filter(
        NodStudent.org_id == org_id).group_by(NodStudent.current_level).all()
    recent_students = db.query(NodStudent).filter(NodStudent.org_id == org_id
        ).order_by(desc(NodStudent.created_at)).limit(20).all()
    recent_sessions = db.query(NodSession).filter(NodSession.org_id == org_id
        ).order_by(desc(NodSession.session_date)).limit(20).all()
    unpaid_coaching = db.query(NodCoaching).filter(
        NodCoaching.org_id == org_id, NodCoaching.paid == False
        ).order_by(desc(NodCoaching.session_date)).limit(10).all()

    return templates.TemplateResponse("nod_dashboard.html", {
        "request": request, "user": user,
        "active_students": active_students, "total_sessions": total_sessions,
        "total_coaching_revenue": total_coaching_revenue, "level_dist": level_dist,
        "recent_students": recent_students, "recent_sessions": recent_sessions,
        "unpaid_coaching": unpaid_coaching,
    })


# ── Products Dashboard ──

PRODUCT_LADDER = [
    {"name": "NOD Academy Book (Amazon)", "price": 10, "status": "done",
     "desc": "NOD Academy — available on Amazon", "link": "",
     "buy_link": "https://www.amazon.com/dp/B0H6T2M995"},
    {"name": "PDF Cheat Sheet (50 Labels)", "price": 9, "status": "wip",
     "desc": "50 labeled phrases that make people open up", "link": ""},
    {"name": "Negotiation Flash Cards", "price": 19, "status": "todo",
     "desc": "Physical or digital deck of NOD tools", "link": ""},
    {"name": "Bare Knuckle Negotiation App", "price": 29, "status": "done",
     "desc": "NOD-ify app — 23 tools, timed sessions", "link": "https://dan8nod.github.io/NOD-ify/MixMatch-FV3.html"},
    {"name": "Negotiation Field Manual", "price": 49, "status": "done",
     "desc": "Your NOD Academy ebook — 33 chapters", "link": "",
     "buy_link": "https://dancruzpro.gumroad.com/l/bksozf"},
    {"name": "RE Scripts Pack", "price": 99, "status": "done",
     "desc": "Real estate negotiation scripts", "link": "",
     "buy_link": "https://dancruzpro.gumroad.com/l/fxgdpc"},
    {"name": "Complete Bundle", "price": 149, "status": "todo",
     "desc": "All digital products in one package", "link": ""},
    {"name": "NOD Membership", "price": 199, "status": "todo",
     "desc": "Ongoing group coaching + community", "link": "", "recurring": True},
    {"name": "Self-Paced Course", "price": 299, "status": "todo",
     "desc": "Recorded Saturday sessions + toolkit", "link": ""},
    {"name": "Advanced Masterclass", "price": 499, "status": "todo",
     "desc": "Deep dive: Level 3 tools, storytelling", "link": ""},
    {"name": "Private Coaching — $500/hr", "price": 500, "status": "done",
     "desc": "1-on-1 negotiation coaching. 60 minutes, live via Zoom. Bring a real deal, leave with a playbook.",
     "link": "",
     "buy_link": "https://calendly.com/negotiatorsondemand/virtualcoffeewithdan"},
    {"name": "Quick Consult — $49", "price": 49, "status": "done",
     "desc": "30-min intro call. One question, one tactical answer.",
     "link": "",
     "buy_link": "https://calendly.com/negotiatorsondemand/30min"},
    {"name": "Deep Dive — $200", "price": 200, "status": "done",
     "desc": "60-min deep strategy session. Multiple scenarios, full playbook.",
     "link": "",
     "buy_link": "https://calendly.com/negotiatorsondemand/60min"},
    {"name": "Corporate Training", "price": 2500, "status": "todo",
     "desc": "Half-day or full-day team workshops", "link": ""},
    {"name": "Business Workshop", "price": 5000, "status": "todo",
     "desc": "Executive-level negotiation intensive", "link": ""},
    {"name": "Enterprise Consulting", "price": 10000, "status": "todo",
     "desc": "Retained advisory for sales teams", "link": ""},
]

STATUS_MAP = {"done": "✅ Shipped", "wip": "🔧 Building", "todo": "📋 Planned"}


@router.get("/products", response_class=HTMLResponse)
async def products_dashboard(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    org_id = user.org_id
    settings = get_settings()
    stripe_configured = bool(settings.stripe_secret_key)

    # ── Real DB stats ──
    now = datetime.now(timezone.utc)
    month_ago = now - timedelta(days=30)

    total_students = db.query(NodStudent).filter(NodStudent.org_id == org_id).count()
    active_students = db.query(NodStudent).filter(
        NodStudent.org_id == org_id, NodStudent.status == NodStudentStatus.ACTIVE).count()
    total_sessions = db.query(NodSession).filter(NodSession.org_id == org_id).count()
    sessions_30d = db.query(NodSession).filter(
        NodSession.org_id == org_id, NodSession.session_date >= month_ago).count()

    # Coaching revenue
    coaching_revenue_cents = db.query(func.coalesce(func.sum(NodCoaching.amount_cents), 0)).filter(
        NodCoaching.org_id == org_id, NodCoaching.paid == True).scalar()
    coaching_revenue_30d_cents = db.query(func.coalesce(func.sum(NodCoaching.amount_cents), 0)).filter(
        NodCoaching.org_id == org_id, NodCoaching.paid == True,
        NodCoaching.session_date >= month_ago).scalar()
    unpaid_count = db.query(NodCoaching).filter(
        NodCoaching.org_id == org_id, NodCoaching.paid == False).count()

    # Level distribution
    level_dist = db.query(NodStudent.current_level, func.count(NodStudent.id)).filter(
        NodStudent.org_id == org_id).group_by(NodStudent.current_level).all()

    # Sessions by type
    sessions_by_type = db.query(NodSession.session_type, func.count(NodSession.id)).filter(
        NodSession.org_id == org_id).group_by(NodSession.session_type).all()

    # Most practiced tools
    tools_raw = db.query(NodSession.tools_practiced).filter(
        NodSession.org_id == org_id, NodSession.tools_practiced.isnot(None)).all()
    tool_counts = {}
    for (tools_str,) in tools_raw:
        for t in tools_str.split(","):
            t = t.strip()
            if t:
                tool_counts[t] = tool_counts.get(t, 0) + 1
    top_tools = sorted(tool_counts.items(), key=lambda x: -x[1])[:10]

    # Student growth (monthly) — ponytail: dialect-agnostic (works on sqlite + pg)
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        growth_sql = "SELECT TO_CHAR(created_at, 'YYYY-MM') AS month, COUNT(*) AS cnt FROM nod_students WHERE org_id = :oid GROUP BY month ORDER BY month"
    else:
        growth_sql = "SELECT strftime('%Y-%m', created_at) AS month, COUNT(*) AS cnt FROM nod_students WHERE org_id = :oid GROUP BY month ORDER BY month"
    growth_raw = db.execute(sa_text(growth_sql), {"oid": org_id}).all()

    return templates.TemplateResponse("nod_products.html", {
        "request": request, "user": user,
        "products": PRODUCT_LADDER,
        "status_map": STATUS_MAP,
        "stripe_configured": stripe_configured,
        # DB stats
        "total_students": total_students,
        "active_students": active_students,
        "total_sessions": total_sessions,
        "sessions_30d": sessions_30d,
        "coaching_revenue_cents": coaching_revenue_cents,
        "coaching_revenue_30d_cents": coaching_revenue_30d_cents,
        "unpaid_count": unpaid_count,
        "level_dist": level_dist,
        "sessions_by_type": sessions_by_type,
        "top_tools": top_tools,
        "growth_raw": growth_raw,
    })


# ── Stripe proxy (server-side, key never reaches frontend) ──

@router.get("/api/stripe/status")
async def stripe_status(user: User = Depends(require_user)):
    settings = get_settings()
    return {"configured": bool(settings.stripe_secret_key)}


@router.get("/api/stripe/balance")
async def stripe_balance(user: User = Depends(require_user)):
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(400, "Stripe not configured. Set STRIPE_SECRET_KEY in env.")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.stripe.com/v1/balance",
            headers={"Authorization": f"Bearer {settings.stripe_secret_key}"},
        )
        return r.json()


@router.get("/api/stripe/charges")
async def stripe_charges(limit: int = 20, user: User = Depends(require_user)):
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(400, "Stripe not configured.")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://api.stripe.com/v1/charges?limit={limit}",
            headers={"Authorization": f"Bearer {settings.stripe_secret_key}"},
        )
        return r.json()


@router.get("/api/stripe/payouts")
async def stripe_payouts(limit: int = 10, user: User = Depends(require_user)):
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(400, "Stripe not configured.")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://api.stripe.com/v1/payouts?limit={limit}",
            headers={"Authorization": f"Bearer {settings.stripe_secret_key}"},
        )
        return r.json()


# ── Student API ──

@router.get("/api/nod/students")
async def list_students(
    user: User = Depends(require_user), db: Session = Depends(get_db),
    level: str = Query(None), status: str = Query(None),
):
    q = db.query(NodStudent).filter(NodStudent.org_id == user.org_id)
    if level: q = q.filter(NodStudent.current_level == level.upper())
    if status: q = q.filter(NodStudent.status == status.upper())
    students = q.order_by(desc(NodStudent.created_at)).all()
    return [{"id": s.id, "name": s.name, "email": s.email, "phone": s.phone,
        "current_level": s.current_level.value, "sessions_completed": s.sessions_completed,
        "status": s.status.value, "source": s.source, "notes": s.notes,
        "created_at": s.created_at.isoformat() if s.created_at else None} for s in students]


@router.post("/api/nod/students")
async def create_student(body: dict = Body(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    s = NodStudent(org_id=user.org_id, name=body.get("name"), email=body.get("email"),
                   phone=body.get("phone"), source=body.get("source"), notes=body.get("notes"))
    db.add(s); db.commit(); db.refresh(s)
    return {"id": s.id, "name": s.name}


@router.get("/api/nod/sessions")
async def list_sessions(user: User = Depends(require_user), db: Session = Depends(get_db), student_id: int = Query(None)):
    q = db.query(NodSession).filter(NodSession.org_id == user.org_id)
    if student_id: q = q.filter(NodSession.student_id == student_id)
    sessions = q.order_by(desc(NodSession.session_date)).limit(50).all()
    return [{"id": s.id, "student_id": s.student_id, "session_type": s.session_type.value,
        "session_date": s.session_date.isoformat() if s.session_date else None,
        "tools_practiced": s.tools_practiced, "level_focus": s.level_focus.value if s.level_focus else None,
        "duration_minutes": s.duration_minutes, "notes": s.notes} for s in sessions]


@router.post("/api/nod/sessions")
async def create_session(body: dict = Body(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    session = NodSession(org_id=user.org_id, student_id=body["student_id"],
        session_type=body["session_type"],
        session_date=datetime.fromisoformat(body["session_date"]) if isinstance(body.get("session_date"), str) else datetime.now(timezone.utc),
        tools_practiced=body.get("tools_practiced"), level_focus=body.get("level_focus"),
        duration_minutes=body.get("duration_minutes"), notes=body.get("notes"))
    db.add(session)
    student = db.query(NodStudent).filter(NodStudent.id == body["student_id"]).first()
    if student: student.sessions_completed = (student.sessions_completed or 0) + 1
    db.commit(); db.refresh(session)
    return {"id": session.id}


@router.get("/api/nod/coaching")
async def list_coaching(user: User = Depends(require_user), db: Session = Depends(get_db), unpaid_only: bool = Query(False)):
    q = db.query(NodCoaching).filter(NodCoaching.org_id == user.org_id)
    if unpaid_only: q = q.filter(NodCoaching.paid == False)
    coaching = q.order_by(desc(NodCoaching.session_date)).limit(50).all()
    return [{"id": c.id, "student_id": c.student_id,
        "session_date": c.session_date.isoformat() if c.session_date else None,
        "topic": c.topic, "amount_cents": c.amount_cents, "paid": c.paid,
        "paid_at": c.paid_at.isoformat() if c.paid_at else None, "notes": c.notes} for c in coaching]


@router.post("/api/nod/coaching")
async def create_coaching(body: dict = Body(...), user: User = Depends(require_user), db: Session = Depends(get_db)):
    c = NodCoaching(org_id=user.org_id, student_id=body["student_id"],
        session_date=datetime.fromisoformat(body["session_date"]) if isinstance(body.get("session_date"), str) else datetime.now(timezone.utc),
        topic=body.get("topic"), amount_cents=body.get("amount_cents"), paid=body.get("paid", False), notes=body.get("notes"))
    db.add(c); db.commit(); db.refresh(c)
    return {"id": c.id}
