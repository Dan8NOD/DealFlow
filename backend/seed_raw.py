"""
Raw psycopg2 seed — no FastAPI app imports, no env var interception.
Reads from local SQLite, writes to Render PostgreSQL directly.
"""
import sqlite3, sys
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_values

PG_CONN_FILE = "/tmp/pg_conn.txt"

def load_pg_params():
    params = {}
    with open(PG_CONN_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                params[k.strip()] = v.strip()
    return params

SQLITE = "/Users/danielcruz/Desktop/Leads/saas/backend/renter_portal.db"
NOW    = datetime.utcnow().isoformat()

def ts(v): return v or NOW

def main():
    print("Connecting to Render PostgreSQL...")
    pg = psycopg2.connect(**load_pg_params())
    pg.autocommit = False
    cur = pg.cursor()
    print("Connected.")

    src = sqlite3.connect(f"file:{SQLITE}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    # ── Create tables (minimal DDL matching the ORM) ─────────────────────────
    print("Creating tables...")
    # Drop and recreate to fix any type mismatches from first run
    cur.execute("""
    DROP TABLE IF EXISTS property_files, application_events, email_messages,
        email_accounts, cma_requests, sales_deals, applications,
        leads, properties, users, organizations CASCADE;
    DROP TYPE IF EXISTS plantier, userrole, propertystatus, leadstatus,
        applicationstatus, salesstatus CASCADE;
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS organizations (
        id SERIAL PRIMARY KEY,
        name VARCHAR(200) NOT NULL,
        plan VARCHAR(20) DEFAULT 'PRO',
        created_at TIMESTAMP DEFAULT NOW(),
        stripe_customer_id VARCHAR(100)
    );
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        org_id INTEGER NOT NULL REFERENCES organizations(id),
        email VARCHAR(200) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        full_name VARCHAR(200),
        role VARCHAR(20) DEFAULT 'OWNER',
        is_active BOOLEAN DEFAULT true,
        email_verified BOOLEAN DEFAULT false,
        created_at TIMESTAMP DEFAULT NOW(),
        last_login_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS properties (
        id SERIAL PRIMARY KEY,
        org_id INTEGER NOT NULL REFERENCES organizations(id),
        address VARCHAR(300) NOT NULL,
        unit VARCHAR(50),
        city VARCHAR(100),
        state VARCHAR(2),
        zip_code VARCHAR(10),
        bedrooms FLOAT,
        bathrooms FLOAT,
        square_feet INTEGER,
        rent FLOAT,
        status VARCHAR(20) DEFAULT 'AVAILABLE',
        tenant_name VARCHAR(200),
        available_date TIMESTAMP,
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS leads (
        id SERIAL PRIMARY KEY,
        org_id INTEGER NOT NULL REFERENCES organizations(id),
        property_id INTEGER REFERENCES properties(id),
        name VARCHAR(200),
        email VARCHAR(200),
        phone VARCHAR(50),
        source VARCHAR(100),
        status VARCHAR(20) DEFAULT 'NEW',
        subject TEXT,
        received_at TIMESTAMP NOT NULL,
        days_old INTEGER,
        raw_email_id VARCHAR(200),
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS applications (
        id SERIAL PRIMARY KEY,
        org_id INTEGER NOT NULL REFERENCES organizations(id),
        property_id INTEGER REFERENCES properties(id),
        unit VARCHAR(50),
        applicant_name VARCHAR(200),
        status VARCHAR(30) DEFAULT 'APPLICATION_RECEIVED',
        handler VARCHAR(200),
        first_seen TIMESTAMP,
        last_update TIMESTAMP,
        days_in_pipeline INTEGER DEFAULT 0,
        event_count INTEGER DEFAULT 0,
        needs_review BOOLEAN DEFAULT false,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS sales_deals (
        id SERIAL PRIMARY KEY,
        org_id INTEGER NOT NULL REFERENCES organizations(id),
        property_address VARCHAR(300) NOT NULL,
        status VARCHAR(30) DEFAULT 'ACTIVE_LISTING',
        list_price FLOAT,
        transaction_coordinator VARCHAR(200),
        first_seen TIMESTAMP,
        last_update TIMESTAMP,
        days_idle INTEGER DEFAULT 0,
        event_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS cma_requests (
        id SERIAL PRIMARY KEY,
        org_id INTEGER NOT NULL REFERENCES organizations(id),
        property_address VARCHAR(300) NOT NULL,
        unit VARCHAR(50),
        kind VARCHAR(20),
        status VARCHAR(30) DEFAULT 'pending',
        request_count INTEGER DEFAULT 1,
        first_request TIMESTAMP,
        last_request TIMESTAMP,
        listed_at TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS email_accounts (
        id SERIAL PRIMARY KEY,
        org_id INTEGER NOT NULL REFERENCES organizations(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        provider VARCHAR(20) NOT NULL,
        email_address VARCHAR(200) NOT NULL,
        access_token TEXT,
        refresh_token TEXT,
        token_expires_at TIMESTAMP,
        last_sync_at TIMESTAMP,
        sync_cursor VARCHAR(200),
        is_active BOOLEAN DEFAULT true,
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS email_messages (
        id SERIAL PRIMARY KEY,
        org_id INTEGER NOT NULL REFERENCES organizations(id),
        email_account_id INTEGER REFERENCES email_accounts(id),
        external_id VARCHAR(200) UNIQUE,
        subject TEXT,
        sender_email VARCHAR(200),
        sender_name VARCHAR(200),
        received_at TIMESTAMP,
        body_preview TEXT,
        is_processed BOOLEAN DEFAULT false,
        matched_property_id INTEGER REFERENCES properties(id),
        matched_kind VARCHAR(30),
        created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS application_events (
        id SERIAL PRIMARY KEY,
        application_id INTEGER NOT NULL REFERENCES applications(id),
        event_type VARCHAR(50) NOT NULL,
        occurred_at TIMESTAMP NOT NULL,
        handler VARCHAR(200),
        source_email_id VARCHAR(200),
        subject TEXT
    );
    CREATE TABLE IF NOT EXISTS property_files (
        id SERIAL PRIMARY KEY,
        org_id INTEGER NOT NULL REFERENCES organizations(id),
        property_id INTEGER REFERENCES properties(id),
        kind VARCHAR(30),
        name VARCHAR(500),
        path VARCHAR(1000),
        source VARCHAR(50),
        size_bytes INTEGER,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    pg.commit()
    print("Tables created.")

    # ── Org ───────────────────────────────────────────────────────────────────
    cur.execute("SELECT id FROM organizations WHERE name='Leads Realty'")
    row = cur.fetchone()
    if row:
        org_id = row[0]
        print(f"Org exists id={org_id}")
    else:
        cur.execute("INSERT INTO organizations (name, plan) VALUES ('Leads Realty','PRO') RETURNING id")
        org_id = cur.fetchone()[0]
        pg.commit()
        print(f"Org created id={org_id}")

    # ── User ──────────────────────────────────────────────────────────────────
    cur.execute("SELECT id FROM users WHERE email='dancruzhomes@gmail.com'")
    if not cur.fetchone():
        import bcrypt
        pw = bcrypt.hashpw(b"Leads2025!", bcrypt.gensalt()).decode()
        cur.execute("""INSERT INTO users (org_id,email,password_hash,full_name,role,is_active)
                       VALUES (%s,'dancruzhomes@gmail.com',%s,'Daniel Cruz','OWNER',true)""",
                    (org_id, pw))
        pg.commit()
        print("User created: dancruzhomes@gmail.com")
    else:
        print("User exists")

    # ── Properties ────────────────────────────────────────────────────────────
    rows = src.execute("SELECT * FROM properties WHERE org_id=1").fetchall()
    prop_map = {}
    new_p = skip_p = 0
    for r in rows:
        addr = (r["address"] or "").strip()[:299]
        unit = (r["unit"] or "").strip()[:49]
        if not addr: skip_p += 1; continue
        cur.execute("SELECT id FROM properties WHERE org_id=%s AND address=%s AND unit=%s",
                    (org_id, addr, unit))
        ex = cur.fetchone()
        if ex:
            prop_map[r["id"]] = ex[0]; skip_p += 1; continue
        cur.execute("""INSERT INTO properties (org_id,address,unit,rent,status,tenant_name)
                       VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (org_id, addr, unit, r["rent"], r["status"] or "AVAILABLE",
                     (r["tenant_name"] or "")[:199] or None))
        pid = cur.fetchone()[0]
        prop_map[r["id"]] = pid
        new_p += 1
    pg.commit()
    print(f"Properties: {new_p} new, {skip_p} skipped")

    # ── Leads ─────────────────────────────────────────────────────────────────
    rows = src.execute("SELECT * FROM leads WHERE org_id=1").fetchall()
    new_l = skip_l = 0
    for r in rows:
        em = (r["email"] or "").strip().lower()
        if em:
            cur.execute("SELECT id FROM leads WHERE org_id=%s AND email=%s", (org_id, em))
            if cur.fetchone(): skip_l += 1; continue
        cur.execute("""INSERT INTO leads (org_id,property_id,name,email,phone,source,status,received_at,days_old)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (org_id, prop_map.get(r["property_id"]), r["name"], em,
                     r["phone"], r["source"], r["status"] or "NEW",
                     ts(r["received_at"]), r["days_old"] or 0))
        new_l += 1
    pg.commit()
    print(f"Leads: {new_l} new, {skip_l} skipped")

    # ── Applications ──────────────────────────────────────────────────────────
    rows = src.execute("SELECT * FROM applications WHERE org_id=1").fetchall()
    new_a = skip_a = 0
    for r in rows:
        pid = prop_map.get(r["property_id"])
        unit = (r["unit"] or "").strip()
        aname = (r["applicant_name"] or "").strip()
        status = (r["status"] or "APPLICATION_RECEIVED").strip()
        cur.execute("""SELECT id FROM applications
                       WHERE org_id=%s AND property_id IS NOT DISTINCT FROM %s
                       AND unit=%s AND applicant_name=%s AND status=%s""",
                    (org_id, pid, unit, aname, status))
        if cur.fetchone(): skip_a += 1; continue
        cur.execute("""INSERT INTO applications
                       (org_id,property_id,unit,applicant_name,status,handler,
                        first_seen,last_update,days_in_pipeline,event_count)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (org_id, pid, unit, aname, status, r["handler"],
                     r["first_seen"], r["last_update"],
                     r["days_in_pipeline"] or 0, r["event_count"] or 0))
        new_a += 1
    pg.commit()
    print(f"Applications: {new_a} new, {skip_a} skipped")

    # ── Sales ──────────────────────────────────────────────────────────────────
    rows = src.execute("SELECT * FROM sales_deals WHERE org_id=1").fetchall()
    new_s = skip_s = 0
    for r in rows:
        cur.execute("SELECT id FROM sales_deals WHERE org_id=%s AND property_address=%s",
                    (org_id, r["property_address"]))
        if cur.fetchone(): skip_s += 1; continue
        cur.execute("""INSERT INTO sales_deals
                       (org_id,property_address,status,list_price,
                        first_seen,last_update,days_idle,event_count)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (org_id, r["property_address"], r["status"] or "ACTIVE_LISTING",
                     r["list_price"], r["first_seen"], r["last_update"],
                     r["days_idle"] or 0, r["event_count"] or 0))
        new_s += 1
    pg.commit()
    print(f"Sales deals: {new_s} new, {skip_s} skipped")

    # ── Summary ───────────────────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM properties WHERE org_id=%s", (org_id,))
    tp = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE org_id=%s", (org_id,))
    tl = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM applications WHERE org_id=%s", (org_id,))
    ta = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM sales_deals WHERE org_id=%s", (org_id,))
    ts_ = cur.fetchone()[0]

    cur.close(); pg.close(); src.close()

    print()
    print("=" * 45)
    print("PRODUCTION DB SEEDED")
    print("=" * 45)
    print(f"  Properties  : {tp}")
    print(f"  Leads       : {tl}")
    print(f"  Applications: {ta}")
    print(f"  Sales deals : {ts_}")
    print()
    print("Login at your Render URL:")
    print("  Email    : dancruzhomes@gmail.com")
    print("  Password : Leads2025!")

if __name__ == "__main__":
    main()
