"""
Import Cruz leasing & sales.xlsx into renter_portal.db.
Strategy: MERGE — skip records that already exist by address+unit.

Sheets processed:
  Deals          -> properties (sales listings + active rentals to market)
  Rented         -> properties (placed rentals, historical)
  New Leads Info -> leads (prospect contacts)
  Sales          -> sales_deals (listing pipeline)

Run: python3 import_xlsx.py
"""
import sqlite3
import re
import sys
from pathlib import Path
from datetime import datetime

DB   = Path(__file__).parent / "renter_portal.db"
DATA = Path("/tmp/xlsx_extracted.txt")

NOW = datetime.utcnow().isoformat()

SKIP_ADDRESSES = {
    "sellers", "buyers", "closed", "july", "march", "april", "may", "june",
    "january", "february", "august", "september", "october", "november", "december",
    "address", "unit", "sales", "referral fee %20  with zach", "",
}

def norm(s):
    if not s: return ""
    return re.sub(r'\s+', ' ', str(s).strip()).lower()

def safe_float(s):
    try:
        return float(str(s).replace('$','').replace(',','').strip())
    except Exception:
        return None

# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_org(cur):
    cur.execute("SELECT id FROM organizations LIMIT 1")
    row = cur.fetchone()
    if not row:
        print("ERROR: No organization found. Run initial import first.")
        sys.exit(1)
    return row[0]

def get_or_create_property(cur, org_id, address, unit="", rent=None, status="available"):
    """Return (property_id, created:bool). Skips bad addresses."""
    a = norm(address)
    if a in SKIP_ADDRESSES or len(a) < 4:
        return None, False
    u = str(unit or "").strip()
    cur.execute(
        "SELECT id FROM properties WHERE org_id=? AND lower(trim(address))=? AND trim(unit)=?",
        (org_id, a, u)
    )
    row = cur.fetchone()
    if row:
        return row[0], False
    cur.execute(
        """INSERT INTO properties (org_id, address, unit, rent, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (org_id, address.strip(), u, rent, status, NOW)
    )
    return cur.lastrowid, True

def upsert_lead(cur, org_id, name, email, phone, property_id=None):
    email = norm(email)
    name  = str(name or "").strip()
    phone = str(phone or "").strip()
    if not email and not name:
        return False
    if email:
        cur.execute("SELECT id FROM leads WHERE org_id=? AND lower(trim(email))=?", (org_id, email))
        if cur.fetchone():
            return False   # already exists
    cur.execute(
        """INSERT INTO leads (org_id, property_id, name, email, phone,
               source, status, days_old, received_at, created_at)
           VALUES (?, ?, ?, ?, ?, 'spreadsheet', 'new', 0, ?, ?)""",
        (org_id, property_id, name, email, phone, NOW, NOW)
    )
    return True

def upsert_sales_deal(cur, org_id, address, status="active", list_price=None, notes=""):
    a = norm(address)
    if a in SKIP_ADDRESSES or len(a) < 4:
        return False
    cur.execute(
        "SELECT id FROM sales_deals WHERE org_id=? AND lower(trim(property_address))=?",
        (org_id, a)
    )
    if cur.fetchone():
        return False
    cur.execute(
        """INSERT INTO sales_deals
               (org_id, property_address, status, list_price,
                transaction_coordinator, first_seen, last_update, days_idle, event_count, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?)""",
        (org_id, address.strip(), status, list_price, notes, NOW, NOW, NOW)
    )
    return True

# ──────────────────────────────────────────────────────────────────────────────
# Sheet parsers
# ──────────────────────────────────────────────────────────────────────────────

def split_sheets(lines):
    """Split the extracted text into per-sheet line lists."""
    sheets = {}
    current = None
    for line in lines:
        m = re.match(r'^# ── Sheet: (.+?) ──', line)
        if m:
            current = m.group(1).strip()
            sheets[current] = []
        elif current:
            sheets[current].append(line)
    return sheets

def parse_deals(sheet_lines):
    """
    Deals sheet columns (tab-separated):
    0:Facebook  1:MLS  2:Address  3:Unit  4:Bed  5:Price  6:Available  7:Lockbox  8:BSF  9:Notes
    """
    records = []
    for line in sheet_lines:
        line = line.strip()
        if not line: continue
        parts = [p.strip() for p in line.split('\t')]
        if len(parts) < 3: continue

        fb     = parts[0].upper()
        address = parts[2]
        unit   = parts[3] if len(parts) > 3 else ""
        price_raw = parts[5] if len(parts) > 5 else ""

        # Skip header / section-label rows
        if address.upper() in ("FACEBOOK", "SHOWMOJO", "PROPERTY", "SALES", "UNIT", "BED", "PRICE",
                                "CLOSED DEALS", "JULY", "APRIL", "MAY", "JUNE", "ADDRESS", ""):
            continue
        if re.match(r'^[A-Z\s/]+$', address) and len(address) < 20:
            continue

        price = safe_float(price_raw)

        # Classify
        is_sale = bool(price and price > 50000)
        status_map = {
            "LIVE": "available", "EXECUTE": "available", "WAIT": "available",
            "FINISHED": "rented",  "FOR APPROVAL": "pending",
            "APPROVED APPLICANT": "pending", "CMA": "available",
            "LOAD PICS": "available", "GET LISTING AGREEMENT": "available",
        }
        status = "for_sale" if is_sale else status_map.get(fb, "available")

        records.append(dict(address=address, unit=unit, price=price, status=status, is_sale=is_sale))
    return records

def parse_rented(sheet_lines):
    """
    Rented sheet is messy — scan each row for street addresses.
    """
    records = []
    for line in sheet_lines:
        line = line.strip()
        if not line: continue
        parts = [p.strip() for p in line.split('\t')]

        for i, p in enumerate(parts):
            if re.search(r'\d{2,5}\s+[A-Z]', p, re.IGNORECASE) and \
               any(kw in p.lower() for kw in ['st','ave','blvd','pl','rd','dr','ct',
                                                'ter','ln','way','cir','pkwy','pkwy',
                                                'hickory','saginaw','merrill','drexel',
                                                'wilton','kingston','campbell','sawyer',
                                                'francisco','wentworth','michigan','colfax',
                                                'chappel','ingleside','stewrt','stewart']):
                address = p
                unit = parts[i+1] if i+1 < len(parts) else ""
                price = None
                for j in range(max(0,i-4), min(len(parts),i+8)):
                    v = safe_float(parts[j])
                    if v and 400 < v < 15000:
                        price = v; break
                records.append(dict(address=address, unit=unit, price=price, status="rented"))
                break  # one address per row
    return records

def parse_leads_sheet(sheet_lines):
    """
    New Leads Info: blocks of Name / Phone / Email lines.
    Lines may be multi-column (tab-separated blocks per property).
    """
    # Flatten all tab-separated cells into one big list
    cells = []
    for line in sheet_lines:
        for cell in line.split('\t'):
            cell = cell.strip()
            if cell:
                cells.append(cell)

    leads = []
    i = 0
    while i < len(cells):
        c = cells[i]
        if c.lower().startswith('name:'):
            name = c[5:].strip()
            phone = email = ""
            if i+1 < len(cells) and cells[i+1].lower().startswith('phone:'):
                phone = cells[i+1][6:].strip(); i += 1
            if i+1 < len(cells) and cells[i+1].lower().startswith('email:'):
                email = cells[i+1][6:].strip(); i += 1
            if name or email:
                leads.append(dict(name=name, phone=phone, email=email))
        i += 1
    return leads

def parse_sales_sheet(sheet_lines):
    """
    Sales sheet columns: MLS, front_pic, keys, address, unit, bed/bath, available, sale_amount, notes, owner, tenant
    """
    records = []
    for line in sheet_lines:
        line = line.strip()
        if not line: continue
        parts = [p.strip() for p in line.split('\t')]
        if len(parts) < 4: continue

        address   = parts[3]
        price_raw = parts[7] if len(parts) > 7 else ""
        notes     = parts[8] if len(parts) > 8 else ""

        if not address or norm(address) in SKIP_ADDRESSES:
            continue
        # Skip obvious non-addresses
        if re.match(r'^[A-Z\s%()]+$', address) and len(address) < 25:
            continue

        price = safe_float(price_raw)
        records.append(dict(address=address, price=price, notes=notes))
    return records

# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    for path, name in [(DB, "database"), (DATA, "extracted xlsx text")]:
        if not path.exists():
            print(f"ERROR: {name} not found at {path}")
            sys.exit(1)

    raw = DATA.read_text(encoding="utf-8").splitlines()
    # Strip leading "NNN|" line-number prefixes
    lines = [re.sub(r'^\d+\|', '', l) for l in raw]

    sheets = split_sheets(lines)
    print("Sheets found:", list(sheets.keys()))

    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    org_id = get_org(cur)
    print(f"Org id: {org_id}")

    counters = dict(
        prop_new=0, prop_exist=0,
        lead_new=0, lead_skip=0,
        sale_new=0, sale_skip=0,
    )

    # ── Deals sheet → properties ──
    deals = parse_deals(sheets.get("Deals", []))
    for d in deals:
        pid, created = get_or_create_property(
            cur, org_id, d["address"], d["unit"], d["price"], d["status"]
        )
        if created:
            counters["prop_new"] += 1
            # If it's a sale listing, also create a sales_deal record
            if d["is_sale"]:
                upsert_sales_deal(cur, org_id, d["address"], "active", d["price"])
                counters["sale_new"] += 1
        else:
            counters["prop_exist"] += 1
    print(f"Deals sheet: {counters['prop_new']} properties added, {counters['prop_exist']} already existed")

    # ── Rented sheet → properties ──
    rented = parse_rented(sheets.get("Rented", []))
    rent_new = rent_exist = 0
    for r in rented:
        pid, created = get_or_create_property(
            cur, org_id, r["address"], r["unit"], r["price"], "rented"
        )
        if created: rent_new += 1
        else: rent_exist += 1
    print(f"Rented sheet: {rent_new} properties added, {rent_exist} already existed")

    # ── New Leads Info sheet → leads ──
    lead_recs = parse_leads_sheet(sheets.get("New Leads Info", []))
    for lr in lead_recs:
        ok = upsert_lead(cur, org_id, lr["name"], lr["email"], lr["phone"])
        if ok: counters["lead_new"] += 1
        else:  counters["lead_skip"] += 1
    print(f"New Leads Info sheet: {counters['lead_new']} leads added, {counters['lead_skip']} skipped (duplicate)")

    # ── Sales sheet → sales_deals ──
    sales = parse_sales_sheet(sheets.get("Sales", []))
    for s in sales:
        # Ensure property exists too
        get_or_create_property(cur, org_id, s["address"], "", s["price"], "for_sale")
        ok = upsert_sales_deal(cur, org_id, s["address"], "active", s["price"], s["notes"])
        if ok: counters["sale_new"] += 1
        else:  counters["sale_skip"] += 1
    print(f"Sales sheet: {counters['sale_new']} sales deals added, {counters['sale_skip']} skipped (duplicate)")

    con.commit()

    # ── Final counts ──
    cur.execute("SELECT COUNT(*) FROM properties WHERE org_id=?", (org_id,))
    total_props = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE org_id=?", (org_id,))
    total_leads = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM sales_deals WHERE org_id=?", (org_id,))
    total_sales = cur.fetchone()[0]

    con.close()

    print("\n══════════════════════════════")
    print("IMPORT COMPLETE")
    print("══════════════════════════════")
    print(f"  Properties now in DB : {total_props}")
    print(f"  Leads now in DB      : {total_leads}")
    print(f"  Sales deals in DB    : {total_sales}")
    print(f"\n  New this run:")
    print(f"    Properties added   : {counters['prop_new'] + rent_new}")
    print(f"    Leads added        : {counters['lead_new']}")
    print(f"    Sales deals added  : {counters['sale_new']}")

if __name__ == "__main__":
    main()
