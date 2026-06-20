"""One-shot seed script for Render production DB."""
import sys, os, sqlite3
from datetime import datetime

PW  = "9Lu6a1LIkvsb2LCRaoip4s3HIItCJpOq"
HOST = "dpg-d8r07amrnols73enu4j0-a.oregon-postgres.render.com"
DB_URL = f"postgresql://renter_portal_db_tsog_user:{PW}@{HOST}/renter_portal_db_tsog?sslmode=require"

os.environ["DATABASE_URL"]  = DB_URL
os.environ["ENVIRONMENT"]   = "production"
os.environ["SECRET_KEY"]    = "tG5yInFQyzUdoU1384xyc3h2nvXiTo60XmRT0e25KStYIeS3LkMWRg"
os.environ["DEBUG"]         = "false"

sys.path.insert(0, "/Users/danielcruz/Desktop/Leads/saas/backend")

from app.db import engine, Base, SessionLocal
from app.models import Organization, User, Property, Lead, Application, SalesDeal, PlanTier, UserRole
from app.auth import hash_password

SQLITE = "/Users/danielcruz/Desktop/Leads/saas/backend/renter_portal.db"

def ts(v):
    return v if v else datetime.utcnow().isoformat()

def main():
    print(f"Connecting to {HOST}...")
    Base.metadata.create_all(bind=engine)
    print("Tables OK")

    src  = sqlite3.connect(f"file:{SQLITE}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    dest = SessionLocal()

    try:
        # Org
        org = dest.query(Organization).filter_by(name="Leads Realty").first()
        if not org:
            org = Organization(name="Leads Realty", plan=PlanTier.PRO)
            dest.add(org); dest.flush()
        print(f"Org id={org.id}")

        # User
        u = dest.query(User).filter_by(email="dancruzhomes@gmail.com").first()
        if not u:
            u = User(org_id=org.id, email="dancruzhomes@gmail.com",
                     password_hash=hash_password("Leads2025!"),
                     full_name="Daniel Cruz", role=UserRole.OWNER, is_active=True)
            dest.add(u); dest.flush()
        print(f"User id={u.id}")

        org_id = org.id
        prop_map = {}

        # Properties
        rows = src.execute("SELECT * FROM properties WHERE org_id=1").fetchall()
        new_p = 0
        for r in rows:
            addr = (r["address"] or "").strip()
            unit = (r["unit"] or "").strip()
            if not addr or len(addr) > 299: continue
            if len(unit) > 49: unit = unit[:49]
            ex = dest.query(Property).filter_by(org_id=org_id, address=addr, unit=unit).first()
            if ex:
                prop_map[r["id"]] = ex.id; continue
            p = Property(org_id=org_id, address=addr, unit=unit,
                         rent=r["rent"], status=r["status"],
                         tenant_name=(r["tenant_name"] or "")[:199] or None)
            dest.add(p); dest.flush()
            prop_map[r["id"]] = p.id
            new_p += 1
        print(f"Properties: {new_p} new / {len(rows)-new_p} skipped")

        # Leads
        rows = src.execute("SELECT * FROM leads WHERE org_id=1").fetchall()
        new_l = 0
        for r in rows:
            em = (r["email"] or "").strip().lower()
            if em:
                if dest.query(Lead).filter_by(org_id=org_id, email=em).first(): continue
            l = Lead(org_id=org_id, property_id=prop_map.get(r["property_id"]),
                     name=r["name"], email=em, phone=r["phone"],
                     source=r["source"], status=r["status"],
                     received_at=ts(r["received_at"]), days_old=r["days_old"] or 0)
            dest.add(l); new_l += 1
        dest.flush()
        print(f"Leads: {new_l} new")

        # Applications
        rows = src.execute("SELECT * FROM applications WHERE org_id=1").fetchall()
        new_a = 0
        for r in rows:
            pid = prop_map.get(r["property_id"])
            ex = dest.query(Application).filter_by(
                org_id=org_id, property_id=pid,
                unit=r["unit"] or "", applicant_name=r["applicant_name"] or "",
                status=r["status"]).first()
            if ex: continue
            a = Application(org_id=org_id, property_id=pid,
                            unit=r["unit"], applicant_name=r["applicant_name"],
                            status=r["status"], handler=r["handler"],
                            first_seen=r["first_seen"], last_update=r["last_update"],
                            days_in_pipeline=r["days_in_pipeline"] or 0,
                            event_count=r["event_count"] or 0)
            dest.add(a); new_a += 1
        dest.flush()
        print(f"Applications: {new_a} new")

        # Sales
        rows = src.execute("SELECT * FROM sales_deals WHERE org_id=1").fetchall()
        new_s = 0
        for r in rows:
            if dest.query(SalesDeal).filter_by(org_id=org_id,
                    property_address=r["property_address"]).first(): continue
            s = SalesDeal(org_id=org_id, property_address=r["property_address"],
                          status=r["status"], list_price=r["list_price"],
                          first_seen=r["first_seen"], last_update=r["last_update"],
                          days_idle=r["days_idle"] or 0, event_count=r["event_count"] or 0)
            dest.add(s); new_s += 1
        dest.flush()
        print(f"Sales deals: {new_s} new")

        dest.commit()

        tp = dest.query(Property).filter_by(org_id=org_id).count()
        tl = dest.query(Lead).filter_by(org_id=org_id).count()
        ta = dest.query(Application).filter_by(org_id=org_id).count()
        ts2 = dest.query(SalesDeal).filter_by(org_id=org_id).count()

        print()
        print("=" * 45)
        print("PRODUCTION DB SEEDED SUCCESSFULLY")
        print("=" * 45)
        print(f"  Properties  : {tp}")
        print(f"  Leads       : {tl}")
        print(f"  Applications: {ta}")
        print(f"  Sales deals : {ts2}")
        print()
        print("Login at your Render URL:")
        print("  Email    : dancruzhomes@gmail.com")
        print("  Password : Leads2025!")

    except Exception as e:
        dest.rollback()
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        dest.close(); src.close()

if __name__ == "__main__":
    main()
