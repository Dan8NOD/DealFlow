"""FastAPI entry point."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.db import engine, Base
from app.routers import auth, dashboard, microsoft

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


def _ensure_columns(engine):
    """Add any missing columns that were added after initial table creation."""
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    # Leads table
    lead_cols = {c['name'] for c in insp.get_columns('leads')}
    for col, typ in [('monthly_income','FLOAT'),('income_source','VARCHAR(50)'),
                      ('interested_in_buying','BOOLEAN DEFAULT FALSE'),
                      ('upsell_eligible','BOOLEAN DEFAULT FALSE'),('notes','TEXT')]:
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


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(microsoft.router)


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.environment}


# Serve static frontend (built SPA) in production
try:
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
except RuntimeError:
    pass