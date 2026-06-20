"""Import local data from /Users/danielcruz/Desktop/Leads/ into the SaaS DB.

Usage:
    cd /Users/danielcruz/Desktop/Leads/saas/backend
    export DATABASE_URL=sqlite:///./renter_portal.db
    export SECRET_KEY=any-32...ts

    python -m app.cli.import_local /Users/danielcruz/Desktop/Leads \\
        --admin-email your@email.com \\
        --admin-password "ChooseAStrongPassword1!"

Options:
    --org-name NAME       Organization name (default: derived from folder)
    --admin-email EMAIL    Admin user email (required)
    --admin-password PWD   Admin password (required, 8+ chars)
    --admin-name NAME      Admin full name (default: email)
    --dry-run              Show what would be imported without writing to DB
    --reset                Drop all org data and re-import (DESTRUCTIVE)

Imports:
- Properties (with units as separate rows) from portal_data.json
- Leads from portal_data.json
- Applications + events from applications_data.json
- Sales deals from sales_deals_data.json
- CMA requests from cma_dimitris_data.json
- Property files from property_files_data.json

Idempotent: re-running won't duplicate. Uses email + property address as keys.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make backend/app importable when running as `python -m app.cli.import_local`
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy.orm import Session  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
import bcrypt  # noqa: E402
from app.models import (  # noqa: E402
    Organization, User, UserRole, PlanTier,
    Property, PropertyStatus,
    Lead, LeadStatus,
    Application, ApplicationEvent, ApplicationStatus,
    SalesDeal, SalesStatus,
    CmaRequest, PropertyFile,
)


def hash_password(password: str) -> str:
    # bcrypt has a 72-byte limit; truncate if needed
    pwd_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def normalize_addr(s):
    if not s:
        return ""
    a = s.lower().strip()
    for old, new in [(".", ""), (" street", " st"), (" avenue", " ave"),
                     (" road", " rd"), (" drive", " dr"), (" boulevard", " blvd"),
                     (" place", " pl"), (" terrace", " ter"), (" court", " ct")]:
        a = a.replace(old, new)
    a = " ".join(a.split())
    for city in [" chicago", " calumet city", " riverdale", " dolton", " joliet",
                 " cicero", " naperville", " woodstock", " downers grove",
                 " east", " homewood", " woodridge", " il"]:
        a = a.replace(city, "")
    a = a.replace(", il", "").replace(",il", "").replace(" il", "").strip()
    return a


def parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt[:len(s)+2] if False else fmt)
        except (ValueError, TypeError):
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _to_float(v):
    """Coerce values like '1BA', '2BR', '1,200' to float; None stays None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    # Strip non-numeric suffixes (BA, BR, +, etc.)
    import re as _re
    m = _re.search(r"[\d.]+", s.replace(",", ""))
    return float(m.group()) if m else None


def find_or_create_property(db, org_id, addr, unit="", status="available",
                            rent=None, bedrooms=None, bathrooms=None,
                            tenant="", available=None, notes=""):
    norm = normalize_addr(addr + (f" {unit}" if unit else ""))
    for p in db.query(Property).filter(Property.org_id == org_id).all():
        if normalize_addr(p.address + (f" {p.unit}" if p.unit else "")) == norm:
            return p
    p = Property(
        org_id=org_id, address=addr.strip(), unit=unit.strip() if unit else None,
        status=PropertyStatus(status) if status in PropertyStatus._value2member_map_ else PropertyStatus.AVAILABLE,
        rent=_to_float(rent),
        bedrooms=_to_float(bedrooms),
        bathrooms=_to_float(bathrooms),
        tenant_name=tenant, available_date=parse_dt(available) if available else None,
        notes=notes,
    )
    db.add(p)
    db.flush()
    return p


def import_properties(db, org_id, properties_data, dry_run=False):
    count = 0
    for prop_name, pdata in properties_data.items():
        if not isinstance(pdata, dict):
            continue
        units = pdata.get("units", {})
        if not units:
            # Top-level property without units — still create one row
            if not dry_run:
                find_or_create_property(db, org_id, prop_name)
            count += 1
            continue
        for unit_id, u in units.items():
            if not isinstance(u, dict):
                continue
            status = u.get("status", "available").lower()
            if not dry_run:
                find_or_create_property(
                    db, org_id, prop_name, unit_id,
                    status=status, rent=u.get("rent"),
                    bedrooms=u.get("bedrooms") or u.get("br"),
                    bathrooms=u.get("bathrooms") or u.get("ba"),
                    tenant=u.get("tenant", ""),
                    available=u.get("available"),
                    notes=u.get("notes", ""),
                )
            count += 1
    return count


def import_leads(db, org_id, leads_data, dry_run=False):
    count = 0
    for l in leads_data:
        addr = l.get("property", "")
        unit = l.get("unit", "")
        prop = None
        if not dry_run and addr:
            prop = find_or_create_property(db, org_id, addr, unit)
        if dry_run:
            count += 1
            continue
        # Idempotency by email + subject within last 60 days
        existing = None
        if l.get("email") and l.get("subject"):
            existing = db.query(Lead).filter(
                Lead.org_id == org_id,
                Lead.email == l["email"],
                Lead.subject == l["subject"],
            ).first()
        if existing:
            continue
        received = parse_dt(l.get("received_at")) or parse_dt(l.get("date"))
        if not received:
            received = datetime.now(timezone.utc)
        days_old = l.get("days_ago", 0)
        status = l.get("status", "new").lower()
        try:
            ls = LeadStatus(status)
        except ValueError:
            ls = LeadStatus.NEW
        lead = Lead(
            org_id=org_id, property_id=prop.id if prop else None,
            name=l.get("name"), email=l.get("email"), phone=l.get("phone"),
            source=l.get("platform"), status=ls, subject=l.get("subject"),
            received_at=received, days_old=days_old,
            raw_email_id=str(l.get("message_id", "")) or None,
        )
        db.add(lead)
        count += 1
    return count


def import_applications(db, org_id, apps_data, dry_run=False):
    count = 0
    for a in apps_data:
        addr = a.get("property", "")
        unit = a.get("unit", "")
        if dry_run:
            count += 1
            continue
        prop = find_or_create_property(db, org_id, addr, unit) if addr else None
        status_str = a.get("status", "application_received").lower().replace(" ", "_")
        try:
            status = ApplicationStatus(status_str)
        except ValueError:
            status = ApplicationStatus.APPLICATION_RECEIVED
        existing = db.query(Application).filter(
            Application.org_id == org_id,
            Application.applicant_name == a["applicant"],
            Application.property_id == (prop.id if prop else None),
            Application.unit == unit,
        ).first() if a.get("applicant") else None
        if existing:
            continue
        first_seen = parse_dt(a.get("first_seen"))
        last_update = parse_dt(a.get("last_update"))
        app = Application(
            org_id=org_id,
            property_id=prop.id if prop else None,
            unit=unit or None,
            applicant_name=a.get("applicant"),
            status=status,
            handler=a.get("handler"),
            first_seen=first_seen,
            last_update=last_update,
            days_in_pipeline=a.get("days_in_pipeline", 0),
            event_count=len(a.get("events", [])),
        )
        db.add(app)
        db.flush()
        for ev in a.get("events", []):
            occurred = parse_dt(ev.get("date"))
            if not occurred:
                continue
            db.add(ApplicationEvent(
                application_id=app.id,
                event_type=ev.get("type", "unknown"),
                occurred_at=occurred,
                handler=ev.get("handler"),
                subject=ev.get("subject"),
            ))
        count += 1
    return count


def import_sales_deals(db, org_id, deals_data, dry_run=False):
    count = 0
    for d in deals_data:
        addr = d.get("property", "")
        if not addr:
            continue
        if dry_run:
            count += 1
            continue
        status_str = d.get("status", "active_listing").lower().replace(" ", "_")
        try:
            status = SalesStatus(status_str)
        except ValueError:
            status = SalesStatus.ACTIVE_LISTING
        existing = db.query(SalesDeal).filter(
            SalesDeal.org_id == org_id,
            SalesDeal.property_address == addr,
            SalesDeal.status == status,
        ).first()
        if existing:
            continue
        sd = SalesDeal(
            org_id=org_id, property_address=addr, status=status,
            list_price=d.get("list_price"),
            transaction_coordinator=d.get("transaction_coordinator"),
            first_seen=parse_dt(d.get("first_seen")),
            last_update=parse_dt(d.get("last_update")),
            days_idle=d.get("days_idle", 0),
            event_count=len(d.get("events", [])),
        )
        db.add(sd)
        count += 1
    return count


def import_cmas(db, org_id, cma_records, dry_run=False):
    count = 0
    for c in cma_records:
        addr = c.get("property", "")
        unit = c.get("unit", "")
        if not addr or dry_run:
            count += 1 if dry_run else 0
            continue
        existing = db.query(CmaRequest).filter(
            CmaRequest.org_id == org_id,
            CmaRequest.property_address == addr,
            CmaRequest.unit == unit,
            CmaRequest.kind == c.get("kind", "rental"),
        ).first()
        if existing:
            continue
        db.add(CmaRequest(
            org_id=org_id, property_address=addr, unit=unit or None,
            kind=c.get("kind", "rental"),
            status=c.get("status", "pending"),
            request_count=c.get("request_count", 1),
            first_request=parse_dt(c.get("first_request")),
            last_request=parse_dt(c.get("last_request")),
        ))
        count += 1
    return count


def import_property_files(db, org_id, files_map, dry_run=False):
    count = 0
    for prop_key, pf in files_map.items():
        if not isinstance(pf, dict):
            continue
        for f in pf.get("files", []) + pf.get("obsidian_notes", []):
            if dry_run:
                count += 1
                continue
            # Try to match by address
            prop = None
            for p in db.query(Property).filter(Property.org_id == org_id).all():
                if normalize_addr(p.address + (f" {p.unit}" if p.unit else "")) == normalize_addr(prop_key):
                    prop = p
                    break
            existing = db.query(PropertyFile).filter(
                PropertyFile.org_id == org_id,
                PropertyFile.path == f.get("path"),
            ).first()
            if existing:
                continue
            db.add(PropertyFile(
                org_id=org_id,
                property_id=prop.id if prop else None,
                kind=f.get("kind", "other"),
                name=f.get("name"),
                path=f.get("path"),
                source=f.get("source", "icloud"),
                size_bytes=f.get("size"),
                obsidian_vault=f.get("vault"),
                section=f.get("section"),
            ))
            count += 1
    return count


def main():
    p = argparse.ArgumentParser(description="Import local Renter Portal data into SaaS DB")
    p.add_argument("source", help="Path to local Leads folder (e.g. ~/Desktop/Leads)")
    p.add_argument("--admin-email", required=True)
    p.add_argument("--admin-password", required=True)
    p.add_argument("--admin-name", default=None)
    p.add_argument("--org-name", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--reset", action="store_true",
                   help="DESTRUCTIVE: drop existing org data before importing")
    args = p.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.is_dir():
        print(f"ERROR: {source} is not a directory")
        sys.exit(1)

    # Auto-derive org name from folder if not given
    org_name = args.org_name or source.name.title() + " Realty"
    admin_name = args.admin_name or args.admin_email

    if not args.dry_run:
        # Create tables if missing (dev convenience)
        Base.metadata.create_all(bind=engine)
    else:
        # For dry-run, also need tables to exist for queries
        Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # Reset if requested
        if args.reset and not args.dry_run:
            print("Resetting all org data...")
            db.query(PropertyFile).delete()
            db.query(CmaRequest).delete()
            db.query(ApplicationEvent).delete()
            db.query(Application).delete()
            db.query(SalesDeal).delete()
            db.query(Lead).delete()
            db.query(Property).delete()
            db.query(User).delete()
            db.query(Organization).delete()
            db.commit()

        # Find or create org (by name)
        org = db.query(Organization).filter(Organization.name == org_name).first()
        if not org:
            if args.dry_run:
                org_id = 0
                print(f"  [DRY-RUN] Would create organization: {org_name}")
            else:
                org = Organization(name=org_name, plan=PlanTier.PRO)
                db.add(org)
                db.flush()
                org_id = org.id
                print(f"Created organization: {org_name} (id={org_id})")
        else:
            org_id = org.id
            print(f"Using existing organization: {org_name} (id={org_id})")

        # Find or create admin user
        if not args.dry_run:
            user = db.query(User).filter(User.email == args.admin_email).first()
            if not user:
                user = User(
                    org_id=org_id, email=args.admin_email.lower().strip(),
                    password_hash=hash_password(args.admin_password),
                    full_name=admin_name, role=UserRole.OWNER,
                    email_verified=True,
                )
                db.add(user)
                db.flush()
                print(f"Created admin user: {args.admin_email} (id={user.id})")
            else:
                user.password_hash = hash_password(args.admin_password)
                print(f"Updated password for existing user: {args.admin_email}")

        # Load JSON files
        def load(name):
            p = source / name
            if not p.exists():
                print(f"  [SKIP] {name} not found")
                return {}
            try:
                return json.loads(p.read_text())
            except Exception as e:
                print(f"  [ERROR] {name}: {e}")
                return {}

        portal = load("portal_data.json")
        apps = load("applications_data.json")
        sales = load("sales_deals_data.json")
        cma = load("cma_dimitris_data.json")
        propfiles = load("property_files_data.json")

        print(f"\nLoaded JSON files. Importing...")

        # Properties first (other imports depend on them)
        n_props = import_properties(db, org_id, portal.get("properties", {}), args.dry_run)
        print(f"  Properties: {n_props}")
        n_leads = import_leads(db, org_id, portal.get("leads", []), args.dry_run)
        print(f"  Leads: {n_leads}")
        n_apps = import_applications(db, org_id, apps.get("applications", []), args.dry_run)
        print(f"  Applications: {n_apps}")
        n_sales = import_sales_deals(db, org_id, sales.get("deals", []), args.dry_run)
        print(f"  Sales deals: {n_sales}")
        n_cmas = import_cmas(db, org_id, cma.get("cma_records", []), args.dry_run)
        print(f"  CMA requests: {n_cmas}")
        n_files = import_property_files(db, org_id, propfiles.get("property_files", {}), args.dry_run)
        print(f"  Property files: {n_files}")

        if not args.dry_run:
            db.commit()
            print("\n✓ Import complete.")
        else:
            db.rollback()
            print("\n[DRY-RUN] Nothing was written. Re-run without --dry-run to import.")
    except Exception as e:
        db.rollback()
        print(f"\nERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
