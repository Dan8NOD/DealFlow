"""
Import Cruz leasing & sales.xlsx into renter_portal.db.
Strategy: MERGE — skip records that already exist by address+unit.
Sheets processed:
  Deals     -> properties (sales listings, active rentals)
  Rented    -> properties + applications (rental placements)
  New Leads Info -> leads
  Sales     -> sales_deals
Run: python import_xlsx.py
"""
import sqlite3
import re
import sys
from pathlib import Path
from datetime import datetime

DB = Path(__file__).parent / "renter_portal.db"
XLSX = Path.home() / "Downloads" / "Cruz- leasing & sales.xlsx"

# ── helpers ──────────────────────────────────────────────────────────────────

def normalize(addr):
    if not addr:
        return ""
    addr = str(addr).strip()
    addr = re.sub(r'\s+', ' ', addr)
    return addr.lower()

def get_or_create_property(cur, org_id, address, unit=None, rent=None, status="available", kind="rental"):
    addr = normalize(address)
    if not addr or addr in ("", "sellers", "buyers", "closed", "july", "march", "april", "may", "june"):
        return None
    unit = str(unit).strip() if unit else ""
    cur.execute(
        "SELECT id FROM properties WHERE org_id=? AND lower(trim(address))=? AND trim(unit)=?",
        (org_id, addr, unit)
    )
    row = cur.fetchone()
    if row:
        return row[0]  # already exists
    # insert new
    cur.execute(
        """INSERT INTO properties (org_id, address, unit, rent, status, property_type, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (org_id, address.strip(), unit, rent, status, kind, datetime.utcnow())
    )
    return cur.lastrowid

def upsert_sales_deal(cur, org_id, address, unit, price, status="active", notes=""):
    addr = normalize(address)
    if not addr:
        return
    cur.execute(
        "SELECT id FROM sales_deals WHERE org_id=? AND lower(trim(property_address))=? AND trim(unit)=?",
        (org_id, addr, str(unit or "").strip())
    )
    if cur.fetchone():
        return  # already exists
    prop_id = get_or_create_property(cur, org_id, address, unit, price, status="for_sale", kind="sale")
    cur.execute(
        """INSERT INTO sales_deals (org_id, property_id, property_address, unit, list_price, status, notes, received_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (org_id, prop_id, address.strip(), str(unit or "").strip(),
         price, status, notes, datetime.utcnow(), datetime.utcnow())
    )

def upsert_lead(cur, org_id, name, email, phone, property_id, source="spreadsheet"):
    if not email and not name:
        return
    email = str(email or "").strip().lower()
    if email:
        cur.execute("SELECT id FROM leads WHERE org_id=? AND lower(trim(email))=?", (org_id, email))
        if cur.fetchone():
            return
    cur.execute(
        """INSERT INTO leads (org_id, property_id, name, email, phone, source, status, days_old, received_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'new', 0, ?, ?)""",
        (org_id, property_id, str(name or "").strip(), email,
         str(phone or "").strip(), source, datetime.utcnow(), datetime.utcnow())
    )

# ── sheet parsers ─────────────────────────────────────────────────────────────

DEALS_COLS = {
    "facebook": 0, "mls": 1, "address": 2, "unit": 3,
    "bed": 4, "price": 5, "available": 6, "lockbox": 7,
    "bsf": 8, "notes": 9
}

def parse_deals(lines):
    """Parse Deals sheet rows into property records."""
    records = []
    in_deals = False
    for line in lines:
        line = line.strip()
        if line.startswith("# ── Sheet: Deals"):
            in_deals = True
            continue
        if line.startswith("# ── Sheet:") and in_deals:
            break
        if not in_deals:
            continue
        if not line or line.startswith("Facebook\tMLS") or line.startswith("ShowMojo\tMLS") or line.startswith("CMA\tFINISHED"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue

        # strip leading line number (e.g. "3|Load Pics")
        # lines come pre-numbered with | prefix
        facebook_status = parts[0] if len(parts) > 0 else ""
        mls_status = parts[1] if len(parts) > 1 else ""
        address = parts[2].strip() if len(parts) > 2 else ""
        unit = parts[3].strip() if len(parts) > 3 else ""
        price_raw = parts[5].strip() if len(parts) > 5 else ""
        available = parts[6].strip() if len(parts) > 6 else ""
        notes = parts[9].strip() if len(parts) > 9 else ""

        if not address or address in ("SALES", "Unit", "Closed Deals", "JULY"):
            continue

        # skip header-like rows
        if address.lower() in ("address", "unit", "bed", "price"):
            continue

        # classify as sale vs rental
        try:
            price = float(price_raw) if price_raw else None
        except ValueError:
            price = None

        is_sale = False
        if price and price > 50000:
            is_sale = True
        # check context clues
        if "SALES" in line.upper() and price and price > 50000:
            is_sale = True

        status_map = {
            "LIVE": "available", "EXECUTE": "available", "WAIT": "available",
            "FINISHED": "rented", "FOR APPROVAL": "pending",
            "APPROVED APPLICANT": "pending", "CMA": "available",
            "LOAD PICS": "available", "GET LISTING AGREEMENT": "available",
        }
        fb_upper = facebook_status.upper().strip()
        status = status_map.get(fb_upper, "available")

        records.append({
            "address": address,
            "unit": unit,
            "price": price,
            "status": "for_sale" if is_sale else status,
            "kind": "sale" if is_sale else "rental",
            "notes": notes,
            "available": available,
        })
    return records

def parse_rented(lines):
    """Parse Rented sheet — extract property/rental records."""
    records = []
    in_rented = False
    payout_month = ""
    for line in lines:
        line = line.strip()
        if line.startswith("# ── Sheet: Rented"):
            in_rented = True
            continue
        if line.startswith("# ── Sheet:") and in_rented:
            break
        if not in_rented or not line:
            continue

        # detect payout month markers
        for month in ["JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER",
                      "DECEMBER", "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY"]:
            if month in line.upper() and "PAYOUT" in line.upper():
                payout_month = month
                break

        parts = line.split("\t")
        if len(parts) < 6:
            continue

        # Look for address-like content — try to find a street address in parts
        address = ""
        unit = ""
        price = None
        for i, p in enumerate(parts):
            p = p.strip()
            # Address heuristic: contains a number + street word
            if re.search(r'\d+\s+[A-Z]', p, re.IGNORECASE) and len(p) > 5:
                if any(kw in p.lower() for kw in ['st', 'ave', 'blvd', 'pl', 'rd', 'dr', 'ct', 'ter', 'ln', 'way', 'cir', 'pkwy']):
                    address = p
                    # unit might be next column
                    if i + 1 < len(parts) and parts[i + 1].strip():
                        unit = parts[i + 1].strip()
                    # price might be nearby
                    for j in range(max(0, i - 3), min(len(parts), i + 8)):
                        try:
                            v = float(parts[j].replace('$', '').replace(',', '').strip())
                            if 500 < v < 20000:
                                price = v
                                break
                        except (ValueError, AttributeError):
                            pass
                    break

        if not address:
            continue

        records.append({
            "address": address,
            "unit": unit,
            "price": price,
            "status": "rented",
            "kind": "rental",
            "notes": payout_month,
        })
    return records

def parse_new_leads(lines):
    """Parse New Leads Info sheet — extract name/phone/email blocks."""
    leads = []
    in_leads = False
    current_prop = ""
    i = 0
    flat_lines = []

    for line in lines:
        if line.startswith("# ── Sheet: New Leads Info"):
            in_leads = True
            continue
        if line.startswith("# ── Sheet:") and in_leads:
            break
        if in_leads:
            flat_lines.append(line.strip())

    # Parse name/phone/email triplets
    j = 0
    while j < len(flat_lines):
        line = flat_lines[j]
        if line.lower().startswith("name:"):
            name = line[5:].strip()
            phone = ""
            email = ""
            if j + 1 < len(flat_lines) and flat_lines[j + 1].lower().startswith("phone:"):
                phone = flat_lines[j + 1][6:].strip()
                j += 1
            if j + 1 < len(flat_lines) and flat_lines[j + 1].lower().startswith("email:"):
                email = flat_lines[j + 1][6:].strip()
                j += 1
            if name or email:
                leads.append({"name": name, "phone": phone, "email": email})
        j += 1
    return leads

def parse_sales_sheet(lines):
    """Parse Sales sheet."""
    records = []
    in_sales = False
    for line in lines:
        line = line.strip()
        if line.startswith("# ── Sheet: Sales"):
            in_sales = True
            continue
        if line.startswith("# ── Sheet:") and in_sales:
            break
        if not in_sales or not line:
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        # columns: MLS, front pic, keys, address, unit, bed/bath, available, sale_amount, notes, owner, tenant
        address = parts[3].strip() if len(parts) > 3 else ""
        unit = parts[4].strip() if len(parts) > 4 else ""
        price_raw = parts[7].strip() if len(parts) > 7 else ""
        notes = parts[8].strip() if len(parts) > 8 else ""
        owner = parts[9].strip() if len(parts) > 9 else ""

        if not address or address.upper() in ("SELLERS", "BUYERS", "CLOSED", "ADDRESS"):
            continue
        if re.match(r'^[A-Z\s]+$', address) and len(address) < 15:
            continue

        try:
            price = float(price_raw) if price_raw else None
        except ValueError:
            price = None

        if address and not address.startswith("("):
            records.append({
                "address": address, "unit": unit,
                "price": price, "notes": notes, "owner": owner
            })
    return records

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if not DB.exists():
        print(f"ERROR: Database not found at {DB}")
        sys.exit(1)
    if not XLSX.exists():
        print(f"ERROR: Spreadsheet not found at {XLSX}")
        sys.exit(1)

    # Read the pre-extracted text (already done — passed via stdin or file)
    # We'll read from the extracted text we have
    extracted = Path("/tmp/xlsx_extracted.txt")
    if not extracted.exists():
        print("ERROR: Run extraction first — file /tmp/xlsx_extracted.txt not found")
        sys.exit(1)

    raw_lines = extracted.read_text(encoding="utf-8").splitlines()
    # Strip line-number prefixes (e.g. "3|content" -> "content")
    lines = []
    for l in raw_lines:
        if re.match(r'^\d+\|', l):
            lines.append(l.split('|', 1)[1] if '|' in l else l)
        else:
            lines.append(l)

    con = sqlite3.connect(str(DB))
    cur = con.cursor()

    # Get org_id for first org (Cruz Realty)
    cur.execute("SELECT id FROM organizations LIMIT 1")
    row = cur.fetchone()
    if not row:
        print("ERROR: No organization found in DB. Run initial import first.")
        sys.exit(1)
    org_id = row[0]
    print(f"Using org_id={org_id}")

    # ── Properties from Deals sheet ──
    deals = parse_deals(lines)
    prop_new = 0
    prop_skip = 0
    for d in deals:
        pid = get_or_create_property(
            cur, org_id, d["address"], d["unit"], d["price"],
            status=d["status"], kind=d["kind"]
        )
        if pid:
            prop_new += 1
        else:
            prop_skip += 1
    print(f"Deals sheet: {prop_new} properties added, {prop_skip} skipped (no address)")

    # ── Properties from Rented sheet ──
    rented = parse_rented(lines)
    rent_new = 0
    for r in rented:
        pid = get_or_create_property(
            cur, org_id, r["address"], r["unit"], r["price"],
            status=r["status"], kind=r["kind"]
        )
        if pid:
            rent_new += 1
    print(f"Rented sheet: {rent_new} properties added/found")

    # ── Leads from New Leads Info sheet ──
    lead_records = parse_new_leads(lines)
    leads_new = 0
    for lr in lead_records:
        upsert_lead(cur, org_id, lr["name"], lr["email"], lr["phone"],
                    property_id=None, source="spreadsheet_leads")
        leads_new += 1
    print(f"New Leads Info sheet: {leads_new} leads processed")

    # ── Sales deals from Sales sheet ──
    sales = parse_sales_sheet(lines)
    sales_new = 0
    for s in sales:
        try:
            upsert_sales_deal(cur, org_id, s["address"], s["unit"],
                              s["price"], status="active", notes=s["notes"])
            sales_new += 1
        except Exception as e:
            print(f"  WARN sales deal {s['address']}: {e}")
    print(f"Sales sheet: {sales_new} sales deals processed")

    con.commit()
    con.close()

    print("\nDone. Summary:")
    print(f"  Properties (Deals sheet): {prop_new} new")
    print(f"  Properties (Rented sheet): {rent_new} processed")
    print(f"  Leads: {leads_new} processed")
    print(f"  Sales deals: {sales_new} processed")

if __name__ == "__main__":
    main()
