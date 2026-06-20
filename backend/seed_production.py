"""
Seed the production Render PostgreSQL database with all local data.
Run ONCE after first deploy:
  DATABASE_URL=<render_internal_url> python3 seed_production.py

This script:
1. Creates all tables (Alembic not set up yet — uses create_all)
2. Creates the Leads Realty org + dancruzhomes@gmail.com owner account
3. Imports all properties, leads, applications, and sales deals from local SQLite
"""
import os
import sys
import sqlite3
from datetime import datetime

# Require DATABASE_URL to be set
DB_URL = os.environ.get("DATABASE_URL", "")
if not DB_URL or "render.com" not in DB_URL:
    print("ERROR: Set DATABASE_URL to the Render internal URL before running.")
    print("  export DATABASE_URL='postgresql://...'")
    sys.exit(1)

# Fix URL scheme and ensure SSL (Render mandates it)
DB_URL = DB_URL.replace("postgres://", "postgresql://")
if "sslmode" not in DB_URL:
    DB_URL += "?sslmode=require" if "?" not in DB_URL else "&sslmode=require"

# Bootstrap SQLAlchemy against production DB
os.environ["DATABASE_URL"] = DB_URL
os.environ["ENVIRONMENT"] = "production"
os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY", "temp-for-seed-only")

# Now import app modules (they read DATABASE_URL from env)
sys.path.insert(0, "/Users/danielcruz/Desktop/Leads/saas/backend")
from app.db import engine, Base, SessionLocal
from app.models import (
    Organization, User, Property, Lead, Application,
    SalesDeal, CmaRequest, PlanTier, UserRole
)
from app.auth import hash_password

SQLITE = "/Users/danielcruz/Desktop/Leads/saas/backend/renter_portal.db"

def main():
    print("Creating tables on production DB...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")

    src = sqlite3.connect(f"file:{SQLITE}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    dest = SessionLocal()

    try:
        # ── Org ──────────────────────────────────────────────────────────────
        org = dest.query(Organization).filter_by(name="Leads Realty").first()
        if not org:
            org = Organization(name="Leads Realty", plan=PlanTier.PRO)
            dest.add(org)
            dest.flush()
            print(f"Created org: Leads Realty (id={org.id})")
        else:
            print(f"Org already exists (id={org.id})")

        # ── User ─────────────────────────────────────────────────────────────
        user = dest.query(User).filter_by(email="dancruzhomes@gmail.com").first()
        if not user:
            user = User(
                org_id=org.id,
                email="dancruzhomes@gmail.com",
                password_hash=hash_password("Leads2025!"),
                full_name="Daniel Cruz",
                role=UserRole.OWNER,
                is_active=True,
            )
            dest.add(user)
            dest.flush()
            print(f"Created user: dancruzhomes@gmail.com (id={user.id})")
        else:
            print(f"User already exists (id={user.id})")

        org_id = org.id

        # ── Properties ───────────────────────────────────────────────────────
        rows = src.execute("SELECT * FROM properties WHERE org_id=1").fetchall()
        prop_id_map = {}  # old_id -> new_id
        new_props = 0
        for r in rows:
            exists = dest.query(Property).filter_by(
                org_id=org_id,
                address=r["address"],
                unit=r["unit"] or ""
            ).first()
            if exists:
                prop_id_map[r["id"]] = exists.id
                continue
            p = Property(
                org_id=org_id,
                address=r["address"],
                unit=r["unit"],
                city=r["city"],
                state=r["state"],
                zip_code=r["zip_code"],
                bedrooms=r["bedrooms"],
                bathrooms=r["bathrooms"],
                rent=r["rent"],
                status=r["status"],
                tenant_name=r["tenant_name"],
                notes=r["notes"],
            )
            dest.add(p)
            dest.flush()
            prop_id_map[r["id"]] = p.id
            new_props += 1
        print(f"Properties: {new_props} new, {len(rows)-new_props} skipped")

        # ── Leads ─────────────────────────────────────────────────────────────
        rows = src.execute("SELECT * FROM leads WHERE org_id=1").fetchall()
        new_leads = 0
        for r in rows:
            if r["email"]:
                exists = dest.query(Lead).filter_by(org_id=org_id, email=r["email"]).first()
                if exists:
                    continue
            new_prop_id = prop_id_map.get(r["property_id"])
            l = Lead(
                org_id=org_id,
                property_id=new_prop_id,
                name=r["name"],
                email=r["email"],
                phone=r["phone"],
                source=r["source"],
                status=r["status"],
                subject=r["subject"],
                received_at=r["received_at"] or datetime.utcnow().isoformat(),
                days_old=r["days_old"] or 0,
            )
            dest.add(l)
            new_leads += 1
        dest.flush()
        print(f"Leads: {new_leads} new")

        # ── Applications ──────────────────────────────────────────────────────
        rows = src.execute("SELECT * FROM applications WHERE org_id=1").fetchall()
        new_apps = 0
        for r in rows:
            new_prop_id = prop_id_map.get(r["property_id"])
            exists = dest.query(Application).filter_by(
                org_id=org_id,
                property_id=new_prop_id,
                unit=r["unit"] or "",
                applicant_name=r["applicant_name"],
                status=r["status"],
            ).first()
            if exists:
                continue
            a = Application(
                org_id=org_id,
                property_id=new_prop_id,
                unit=r["unit"],
                applicant_name=r["applicant_name"],
                status=r["status"],
                handler=r["handler"],
                first_seen=r["first_seen"],
                last_update=r["last_update"],
                days_in_pipeline=r["days_in_pipeline"] or 0,
                event_count=r["event_count"] or 0,
            )
            dest.add(a)
            new_apps += 1
        dest.flush()
        print(f"Applications: {new_apps} new")

        # ── Sales Deals ───────────────────────────────────────────────────────
        rows = src.execute("SELECT * FROM sales_deals WHERE org_id=1").fetchall()
        new_sales = 0
        for r in rows:
            exists = dest.query(SalesDeal).filter_by(
                org_id=org_id,
                property_address=r["property_address"]
            ).first()
            if exists:
                continue
            s = SalesDeal(
                org_id=org_id,
                property_address=r["property_address"],
                status=r["status"],
                list_price=r["list_price"],
                transaction_coordinator=r["transaction_coordinator"],
                first_seen=r["first_seen"],
                last_update=r["last_update"],
                days_idle=r["days_idle"] or 0,
                event_count=r["event_count"] or 0,
            )
            dest.add(s)
            new_sales += 1
        dest.flush()
        print(f"Sales deals: {new_sales} new")

        dest.commit()

        # ── Summary ───────────────────────────────────────────────────────────
        total_props = dest.query(Property).filter_by(org_id=org_id).count()
        total_leads = dest.query(Lead).filter_by(org_id=org_id).count()
        total_apps  = dest.query(Application).filter_by(org_id=org_id).count()
        total_sales = dest.query(SalesDeal).filter_by(org_id=org_id).count()

        print()
        print("═" * 40)
        print("PRODUCTION DB SEEDED")
        print("═" * 40)
        print(f"  Properties  : {total_props}")
        print(f"  Leads       : {total_leads}")
        print(f"  Applications: {total_apps}")
        print(f"  Sales deals : {total_sales}")
        print()
        print("Login at your Render URL with:")
        print("  Email   : dancruzhomes@gmail.com")
        print("  Password: Leads2025!")

    except Exception as e:
        dest.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        dest.close()
        src.close()

if __name__ == "__main__":
    main()