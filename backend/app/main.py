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

# Create tables on startup (for SQLite/dev; production uses Alembic)
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


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
