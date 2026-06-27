"""FastAPI entry point — Negotiators on Demand Hub."""
from fastapi import FastAPI, Body
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.db import engine, Base
from app.routers import auth, dashboard, trainer
import os

settings = get_settings()
app = FastAPI(
    title="Negotiators on Demand Hub",
    version="0.1.0",
    debug=settings.debug,
)

# ponytail: serve static files (PDF for nodify graphics tab)
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [settings.base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Create tables on startup
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    from sqlalchemy import text
    from app.db import engine as _engine
    # ponytail: unique index for lead dedup across all sources
    try:
        with _engine.connect() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_leads_org_email "
                "ON leads (org_id, LOWER(email)) WHERE email IS NOT NULL AND email != ''"
            ))
            conn.commit()
    except Exception:
        pass
    _ensure_columns(engine)
    _fix_lowercase_enums(engine)


def _fix_lowercase_enums(engine):
    """Fix: SQLite accepted lowercase enum values, PostgreSQL doesn't. Uppercase them."""
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    if 'leads' not in insp.get_table_names():
        return
    for table, col in {'leads': 'status'}.items():
        if table in insp.get_table_names():
            cols = {c['name'] for c in insp.get_columns(table)}
            if col in cols:
                try:
                    with engine.connect() as conn:
                        conn.execute(text(f"UPDATE {table} SET {col} = UPPER({col}) WHERE {col} != UPPER({col})"))
                        conn.commit()
                except Exception:
                    pass


def _ensure_columns(engine):
    """Add any missing columns that were added after initial table creation."""
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    # Leads table
    if 'leads' in insp.get_table_names():
        lead_cols = {c['name'] for c in insp.get_columns('leads')}
        for col, typ in [
            ('monthly_income', 'FLOAT'),
            ('income_source', 'VARCHAR(50)'),
            ('interested_in_buying', 'BOOLEAN DEFAULT FALSE'),
            ('upsell_eligible', 'BOOLEAN DEFAULT FALSE'),
            ('notes', 'TEXT'),
            ('move_in_date', 'VARCHAR(30)'),
            ('last_called', 'TIMESTAMP'),
            ('call_outcome', 'VARCHAR(100)'),
            ('call_notes', 'TEXT'),
            ('bounce_to', 'TEXT'),
            ('assigned_agent_id', 'INTEGER'),
        ]:
            if col not in lead_cols:
                with engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE leads ADD COLUMN {col} {typ}"))
                    conn.commit()

    # ponytail: indexes on hot path queries
    with engine.connect() as conn:
        for idx in [
            "CREATE INDEX IF NOT EXISTS ix_leads_org_status ON leads(org_id, status)",
        ]:
            conn.execute(text(idx))
        conn.commit()


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(trainer.router)


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.environment}


# Serve static frontend (built SPA) in production
try:
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
except RuntimeError:
    pass