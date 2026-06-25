"""FastAPI entry point."""
from fastapi import FastAPI, Body
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.db import engine, Base
from app.routers import auth, dashboard, microsoft, showings, tenant, files, obsidian, bounce, trainer
import os

settings = get_settings()
app = FastAPI(
    title="Leasing & Sales NOD API",
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

def _seed_demo_data_if_empty(engine):
    """ponytail: Seed demo data if org has no properties/leads. Makes new accounts useful immediately."""
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime, timedelta, timezone
    from app.models import Organization, User, Property, Lead, Application, SalesDeal
    
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        # Find the first org (typically created at signup)
        org = session.query(Organization).first()
        if not org:
            return  # No org, skip
        
        # Check if org already has data
        prop_count = session.query(Property).filter(Property.org_id == org.id).count()
        if prop_count > 0:
            return  # Already has data
        
        # Seed demo data
        now = datetime.now(timezone.utc)
        
        # Demo properties
        props = [
            Property(org_id=org.id, address="3363 S Racine Ave", unit="#1F", city="Chicago", state="IL", rent=1200, bedrooms=2, bathrooms=1, status="AVAILABLE"),
            Property(org_id=org.id, address="4340 Wilson Ave", unit="#2", city="Downers Grove", state="IL", rent=1500, bedrooms=2, bathrooms=1.5, status="AVAILABLE"),
            Property(org_id=org.id, address="1465 E 69th St", unit="#C1", city="Chicago", state="IL", rent=950, bedrooms=1, bathrooms=1, status="RENTED"),
        ]
        session.add_all(props)
        session.flush()
        
        # Demo leads
        leads = [
            Lead(org_id=org.id, property_id=props[0].id, name="Maria Garcia", email="maria@example.com", phone="312-555-0101", source="ShowMojo", status="NEW", received_at=now - timedelta(days=1), monthly_income=4200),
            Lead(org_id=org.id, property_id=props[0].id, name="James Liu", email="james@example.com", phone="312-555-0102", source="Zillow", status="CONTACTED", received_at=now - timedelta(days=3), monthly_income=3800),
            Lead(org_id=org.id, property_id=props[1].id, name="Sarah Ahmed", email="sarah@example.com", phone="312-555-0103", source="Manual", status="NEW", received_at=now - timedelta(hours=6)),
        ]
        session.add_all(leads)
        session.flush()
        
        # Demo applications
        apps = [
            Application(org_id=org.id, property_id=props[2].id, unit="#C1", applicant_name="Robert Kim", status="OFFER_SENT", handler="Dan", first_seen=now - timedelta(days=10), last_update=now - timedelta(days=1), days_in_pipeline=9),
        ]
        session.add_all(apps)
        session.flush()
        
        # Demo sales deals
        deals = [
            SalesDeal(org_id=org.id, property_address="6550 S Drexel Ave", status="ACTIVE_LISTING", list_price=425000, transaction_coordinator="Dan", first_seen=now - timedelta(days=15), last_update=now - timedelta(days=2), days_idle=2),
        ]
        session.add_all(deals)
        
        session.commit()
        print("✓ Demo data seeded")
    except Exception as e:
        session.rollback()
        print(f"! Demo seed failed (non-fatal): {e}")
    finally:
        session.close()


# Create tables on startup
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    # ponytail: add unique constraint on (org_id, email) to stop ShowMojo dupe re-inserts
    # Idempotent — silently skips if index already exists (Postgres/SQLite both)
    from sqlalchemy import text
    from app.db import engine as _engine
    try:
        with _engine.connect() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_leads_org_email "
                "ON leads (org_id, LOWER(email)) WHERE email IS NOT NULL AND email != ''"
            ))
            conn.commit()
    except Exception:
        pass  # already exists or not supported — safe to ignore
    _ensure_columns(engine)
    _fix_lowercase_enums(engine)
    _seed_demo_data_if_empty(engine)


def _fix_lowercase_enums(engine):
    """Fix: SQLite accepted lowercase enum values, PostgreSQL doesn't. Uppercase them."""
    from sqlalchemy import text, inspect
    from app.models import PropertyFile
    insp = inspect(engine)
    
    # Ensure property_files table exists
    if 'property_files' not in insp.get_table_names():
        try:
            PropertyFile.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            # Fallback: create manually
            with engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS property_files (
                        id SERIAL PRIMARY KEY,
                        org_id INTEGER NOT NULL REFERENCES organizations(id),
                        property_id INTEGER REFERENCES properties(id),
                        kind VARCHAR(50),
                        name VARCHAR(500),
                        path VARCHAR(1000),
                        source VARCHAR(50),
                        size_bytes INTEGER,
                        obsidian_vault VARCHAR(50),
                        section VARCHAR(50),
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                conn.commit()
    
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
                      ('call_outcome','VARCHAR(100)'),('call_notes','TEXT'),('bounce_to','TEXT'),
                      # ponytail: assigned_agent_id — added to model but missing from initial migration
                      ('assigned_agent_id','INTEGER')]:
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

    # ponytail: mixmatch_notes — raw SQL CREATE, no ORM model
    if 'mixmatch_notes' not in insp.get_table_names():
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE mixmatch_notes (
                    id SERIAL PRIMARY KEY,
                    note_text TEXT NOT NULL,
                    tool_name VARCHAR(200),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()

    # ponytail: property_updates — weekly reports attached to a property (date-keyed)
    if 'property_updates' not in insp.get_table_names():
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE property_updates (
                    id SERIAL PRIMARY KEY,
                    org_id INTEGER NOT NULL REFERENCES organizations(id),
                    property_id INTEGER REFERENCES properties(id),
                    week_of DATE NOT NULL,
                    summary VARCHAR(200),
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pupdates_property ON property_updates(property_id, week_of DESC)"))
            conn.commit()


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(microsoft.router)
app.include_router(showings.router)
app.include_router(tenant.router)
app.include_router(files.router)
app.include_router(obsidian.router)
app.include_router(bounce.router)
app.include_router(trainer.router)


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.environment}


# Serve static frontend (built SPA) in production
try:
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
except RuntimeError:
    pass