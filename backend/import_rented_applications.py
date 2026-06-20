"""
Second-pass import: create application records for every rented property
that was placed via the Rented sheet.

The Rented sheet is organized by payout month sections. Each row has:
  - address + unit
  - rent price
  - agent/handler (Derek, Israel, Chris, Dan, Zach, etc.)
  - availability / tenant notes
  - payout amounts (BSF split)

We create one application per rented property with:
  - status = moved_in
  - handler = agent name from row
  - first_seen = approximate date from payout month
  - notes preserved

Run: python3 import_rented_applications.py
"""

import sqlite3
import re
import sys
from pathlib import Path
from datetime import datetime, date

DB   = Path(__file__).parent / "renter_portal.db"
DATA = Path("/tmp/xlsx_extracted.txt")
NOW  = datetime.utcnow().isoformat()

MONTH_TO_DATE = {
    "APRIL":     "2024-04-01",
    "MAY":       "2024-05-01",
    "JUNE":      "2024-06-01",
    "JULY":      "2024-07-01",
    "AUGUST":    "2024-08-01",
    "SEPTEMBER": "2024-09-01",
    "OCTOBER":   "2024-10-01",
    "NOVEMBER":  "2024-11-01",
    "DECEMBER":  "2024-12-01",
    "JANUARY":   "2025-01-01",
    "FEBRUARY":  "2025-02-01",
    "MARCH":     "2025-03-01",
}

SKIP_ADDRESSES = {
    "sellers", "buyers", "closed", "july", "march", "april", "may", "june",
    "january", "february", "august", "september", "october", "november", "december",
    "address", "unit", "sales", "", "realtymx", "mls", "video", "front pic",
    "keys", "payed out",
}

# Agent name patterns to extract from cells
AGENT_NAMES = ["derek", "israel", "chris", "dan", "zach", "lamar", "izreon",
               "christopher", "jazmyne", "mando", "jim", "paul"]

def norm(s):
    if not s: return ""
    return re.sub(r'\s+', ' ', str(s).strip()).lower()

def safe_float(s):
    try:
        return float(str(s).replace('$','').replace(',','').strip())
    except Exception:
        return None

def extract_agent(parts):
    """Try to find an agent name in the row cells."""
    for p in parts:
        pl = p.lower().strip()
        for ag in AGENT_NAMES:
            if ag in pl and len(pl) < 40:
                # Clean it up
                for sep in ['-', '/', '&', '+', ',']:
                    pl = pl.replace(sep, ' ')
                words = pl.split()
                agents = [w.title() for w in words if w in AGENT_NAMES]
                if agents:
                    return " / ".join(agents)
    return ""

def extract_bsf(parts):
    """Extract BSF/commission note."""
    for p in parts:
        if "bsf" in p.lower() or "bonus" in p.lower() or "commish" in p.lower():
            return p.strip()[:200]
    return ""

def is_street_address(s):
    if not s: return False
    s = s.strip()
    return bool(
        re.match(r'^\d{2,5}\s+[A-Za-z]', s) and
        any(kw in s.lower() for kw in [
            'st','ave','blvd','pl','rd','dr','ct','ter','ln','way','cir',
            'pkwy','hickory','saginaw','merrill','drexel','wilton','kingston',
            'campbell','sawyer','francisco','wentworth','michigan','colfax',
            'chappel','ingleside','stewart','bogdan','greenbay','lamar',
            'woodlawn','giles','thorton','harbor','atlantic','highland',
            'cottage','luella','eleanor','california','springfield',
            'lemoyne','jackson','clyde','western','wabansia','marion',
            'eberhart','phillips','drexel','loomis','lowe','unity',
            'normal','troy','farwell','sheridan','bunker','rutland',
            'tamarack','shannon','sheehan','naperville','aurora',
        ])
    )

def parse_rented_sheet(lines):
    """
    Parse the Rented sheet into structured deal records.
    Returns list of dicts with: address, unit, rent, agent, bsf_note, payout_month, payout_date
    """
    in_rented = False
    payout_month = "UNKNOWN"
    records = []

    for raw_line in lines:
        # Detect sheet boundaries
        if re.match(r'^# ── Sheet: Rented', raw_line):
            in_rented = True
            continue
        if re.match(r'^# ── Sheet:', raw_line) and in_rented:
            break
        if not in_rented:
            continue

        line = raw_line.strip()
        if not line:
            continue

        # Strip leading line numbers (already done by caller, but be safe)
        line = re.sub(r'^\d+\|', '', line)

        # Detect payout month section headers
        for month in MONTH_TO_DATE:
            if month in line.upper() and ("PAYOUT" in line.upper() or "PAY" in line.upper()):
                payout_month = month
                break

        parts = [p.strip() for p in line.split('\t')]
        if len(parts) < 3:
            continue

        # Skip header rows
        if any(h in parts[0].upper() for h in ["REALTYMX", "MLS", "VIDEO", "FRONT PIC"]):
            if any(h in (parts[1] or "").upper() for h in ["MLS", "VIDEO", "KEYS"]):
                continue  # actual header row

        # Find address in parts
        address = ""
        unit = ""
        rent = None
        addr_idx = -1

        for i, p in enumerate(parts):
            if is_street_address(p):
                address = p
                addr_idx = i
                # Unit is often the next column after address
                if i + 1 < len(parts):
                    candidate = parts[i + 1].strip()
                    # Unit: short alphanumeric like "1.0", "2A", "SFH", "TWH", "G", "3B"
                    if candidate and len(candidate) < 10 and re.match(r'^[\w./\-]+$', candidate):
                        unit = candidate
                break

        if not address:
            continue

        # Extract rent — look for a number between 400 and 10000
        for p in parts:
            v = safe_float(p)
            if v and 400 < v < 10000:
                rent = v
                break

        agent   = extract_agent(parts)
        bsf     = extract_bsf(parts)
        pdate   = MONTH_TO_DATE.get(payout_month, "2024-06-01")

        records.append({
            "address":      address,
            "unit":         unit,
            "rent":         rent,
            "agent":        agent,
            "bsf_note":     bsf,
            "payout_month": payout_month,
            "payout_date":  pdate,
        })

    return records


def main():
    for path, name in [(DB, "database"), (DATA, "extracted xlsx")]:
        if not path.exists():
            print(f"ERROR: {name} not found at {path}")
            sys.exit(1)

    raw = DATA.read_text(encoding="utf-8").splitlines()
    # Strip leading line-number prefixes (e.g. "66|content" -> "content")
    raw = [re.sub(r'^\d+\|', '', l) for l in raw]

    # Find the org
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    cur.execute("SELECT id FROM organizations LIMIT 1")
    org_id = cur.fetchone()[0]
    print(f"Org id: {org_id}")

    records = parse_rented_sheet(raw)
    print(f"Parsed {len(records)} deal rows from Rented sheet")

    created = skipped_no_prop = skipped_exists = 0

    for r in records:
        addr_norm = norm(r["address"])
        unit_norm = r["unit"].strip()

        # Find the matching property
        cur.execute(
            """SELECT id FROM properties
               WHERE org_id=? AND lower(trim(address))=? AND trim(unit)=?""",
            (org_id, addr_norm, unit_norm)
        )
        prop_row = cur.fetchone()
        if not prop_row:
            # Try without unit
            cur.execute(
                "SELECT id FROM properties WHERE org_id=? AND lower(trim(address))=? LIMIT 1",
                (org_id, addr_norm)
            )
            prop_row = cur.fetchone()

        if not prop_row:
            skipped_no_prop += 1
            continue

        prop_id = prop_row[0]

        # Check if an application already exists for this property+unit with moved_in status
        cur.execute(
            """SELECT id FROM applications
               WHERE org_id=? AND property_id=? AND trim(unit)=? AND status='moved_in'""",
            (org_id, prop_id, unit_norm)
        )
        if cur.fetchone():
            skipped_exists += 1
            continue

        # Create the application record
        handler = r["agent"] or "Dan Cruz"
        notes_parts = []
        if r["payout_month"] and r["payout_month"] != "UNKNOWN":
            notes_parts.append(f"Payout: {r['payout_month'].title()}")
        if r["bsf_note"]:
            notes_parts.append(f"BSF: {r['bsf_note']}")
        # Store BSF note in applicant_name placeholder for now (no notes col on applications)
        # We'll use the handler field for agent and applicant_name for bsf context
        applicant_name = " | ".join(notes_parts) if notes_parts else "(rented - from spreadsheet)"

        cur.execute(
            """INSERT INTO applications
                   (org_id, property_id, unit, applicant_name, status,
                    handler, first_seen, last_update, days_in_pipeline, event_count, created_at)
               VALUES (?, ?, ?, ?, 'moved_in', ?, ?, ?, 0, 1, ?)""",
            (org_id, prop_id, unit_norm, applicant_name,
             handler, r["payout_date"], r["payout_date"], NOW)
        )
        created += 1

    con.commit()

    # Final tallies
    cur.execute("SELECT COUNT(*) FROM applications WHERE org_id=? AND status='moved_in'", (org_id,))
    total_moved_in = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM applications WHERE org_id=?", (org_id,))
    total_apps = cur.fetchone()[0]

    con.close()

    print("\n══════════════════════════════════════")
    print("RENTED → APPLICATIONS IMPORT COMPLETE")
    print("══════════════════════════════════════")
    print(f"  Application records created : {created}")
    print(f"  Skipped (no matching prop)  : {skipped_no_prop}")
    print(f"  Skipped (already existed)   : {skipped_exists}")
    print(f"\n  Total applications in DB    : {total_apps}")
    print(f"  Of which moved_in           : {total_moved_in}")
    print()
    print("These closed deals now show in the Applications tab")
    print("and the email parser can match renewal/move-out emails to them.")


if __name__ == "__main__":
    main()
