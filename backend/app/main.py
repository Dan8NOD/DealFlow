"""FastAPI entry point."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.db import engine, Base
from app.routers import auth, dashboard, microsoft, showings, tenant, files, obsidian, bounce

settings = get_settings()
app = FastAPI(
    title="Renter Portal API",
    version="0.1.0",
    debug=settings.debug,
)

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
    _ensure_columns(engine)
    _fix_lowercase_enums(engine)


def _fix_lowercase_enums(engine):
    """Fix: SQLite accepted lowercase enum values, PostgreSQL doesn't. Uppercase them."""
    from sqlalchemy import text, inspect
    from app.models import PropertyFile
    insp = inspect(engine)
    
    # Ensure property_files table exists
    if 'property_files' not in insp.get_table_names():
        PropertyFile.__table__.create(bind=engine, checkfirst=True)
    
    if 'applications' not in insp.get_table_names():
        return
    # Fix applications table
    status_cols = {'applications': 'status', 'leads': 'status', 'properties': 'status',
                   'sales_deals': 'status', 'cma_requests': 'status'}
    for table, col in status_cols.items():
        if table in insp.get_table_names():
            cols = {c['name'] for c in insp.get_columns(table)}
            if col in cols:
                try:
                    with engine.connect() as conn:
                        conn.execute(text(f"UPDATE {table} SET {col} = UPPER({col}) WHERE {col} != UPPER({col})"))
                        conn.commit()
                except Exception:
                    pass  # Table might not have the column or no rows to fix


def _ensure_columns(engine):
    """Add any missing columns that were added after initial table creation."""
    from sqlalchemy import text, inspect
    from app.models import PropertyFile
    insp = inspect(engine)
    # Leads table
    lead_cols = {c['name'] for c in insp.get_columns('leads')}
    for col, typ in [('monthly_income','FLOAT'),('income_source','VARCHAR(50)'),
                      ('interested_in_buying','BOOLEAN DEFAULT FALSE'),
                      ('upsell_eligible','BOOLEAN DEFAULT FALSE'),('notes','TEXT'),
                      # New call-tracking fields
                      ('move_in_date','VARCHAR(30)'),('last_called','TIMESTAMP'),
                      ('call_outcome','VARCHAR(100)'),('call_notes','TEXT'),('bounce_to','TEXT')]:
        if col not in lead_cols:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE leads ADD COLUMN {col} {typ}"))
                conn.commit()
    # Applications table
    app_cols = {c['name'] for c in insp.get_columns('applications')}
    for col, typ in [('monthly_income','FLOAT'),('credit_score','INTEGER'),
                      ('move_in_date','VARCHAR(30)'),('pets','VARCHAR(100)'),('notes','TEXT')]:
        if col not in app_cols:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE applications ADD COLUMN {col} {typ}"))
                conn.commit()
    # Properties table — new Obsidian-enriched fields
    prop_cols = {c['name'] for c in insp.get_columns('properties')}
    for col, typ in [('pet_restrictions','TEXT'),('utilities_included','TEXT'),
                      ('utilities_paid_by_tenant','TEXT'),('parking','TEXT'),
                      ('storage','TEXT'),('laundry','TEXT'),
                      ('asset_manager','VARCHAR(200)'),('lockbox_code','VARCHAR(100)'),
                      ('listing_description','TEXT'),('mls_id','VARCHAR(50)'),
                      ('cma_link','TEXT'),('showing_instructions','TEXT')]:
        if col not in prop_cols:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE properties ADD COLUMN \"{col}\" {typ}"))
                conn.commit()


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(microsoft.router)
app.include_router(showings.router)
app.include_router(tenant.router)
app.include_router(files.router)
app.include_router(obsidian.router)
app.include_router(bounce.router)


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.environment}


# Serve static frontend (built SPA) in production
try:
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
except RuntimeError:
    pass