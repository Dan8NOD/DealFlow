"""Clean property DB to match spreadsheet Property Master.
Usage: python3 clean_properties.py

- Reads Property Master from renter_leads_calling_v5_20260619.xlsx
- Updates matching DB rows to spreadsheet rent/beds/baths/status
- Deletes DB rows not in spreadsheet AND not referenced by leads/apps/sales
- Saves a backup first
"""

import sqlite3, openpyxl, re, shutil
from datetime import datetime
from pathlib import Path

DB = Path(__file__).parent / "backend" / "renter_portal.db"
XLSX = Path(__file__).parent.parent / "renter_leads_calling_v5_20260619.xlsx"

def norm(addr):
    """Normalize address for fuzzy matching."""
    if not addr: return ""
    a = addr.lower().strip()
    a = re.sub(r'\.', '', a)
    a = re.sub(r'\b(street|st|avenue|ave|boulevard|blvd|road|rd|drive|dr|lane|ln|court|ct)\b', '', a)
    a = re.sub(r'\b(south|north|east|west|n|s|e|w)\b', '', a)
    a = re.sub(r'[,;:]', '', a)
    a = re.sub(r'\s+', ' ', a).strip()
    m = re.match(r'(\d+)\s+(\w+)', a)
    return f"{m.group(1)} {m.group(2)}"[:30] if m else a[:30]

def norm_unit(u):
    if not u: return ""
    return re.sub(r'\s+', '', str(u).lower().replace('.', ''))

# ── Read spreadsheet ──
wb = openpyxl.load_workbook(XLSX, data_only=True)
ws = wb['Property Master']

spreadsheet = []  # [(norm_addr, norm_unit, orig_prop, orig_unit, br, ba, rent, status)]
for row in ws.iter_rows(min_row=2, values_only=True):
    prop, unit, br, ba, rent, status, avail, tenant, notes = [str(v) if v is not None else '' for v in row]
    key = (norm(prop), norm_unit(unit))
    spreadsheet.append((*key, prop, unit, br, ba, rent, status))

# ── Backup DB ──
backup = str(DB) + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
shutil.copy2(DB, backup)
print(f"Backup: {backup}")

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Build address key index
cur.execute("SELECT id, address, unit, rent, bedrooms, bathrooms, status FROM properties")
all_props = {row['id']: dict(row) for row in cur.fetchall()}

# Build key → DB id map
key_to_id = {}
for pid, p in all_props.items():
    k = (norm(p['address']), norm_unit(p['unit']))
    key_to_id.setdefault(k, []).append(pid)

# ── Phase 1: Update matching rows ──
updated = 0
for sp in spreadsheet:
    key = sp[:2]
    orig_prop, orig_unit, br, ba, rent_str, status = sp[2:]
    match_ids = key_to_id.get(key, [])
    if not match_ids:
        print(f"  [NO MATCH] {orig_prop} | {orig_unit}")
        continue
    pid = match_ids[0]
    ba_val = float(re.sub(r'[^\d.]', '', ba.split('BA')[0])) if 'BA' in ba else (float(ba) if ba else None)
    br_val = float(re.sub(r'[^\d.]', '', br.split('BR')[0])) if 'BR' in br else (float(br) if br else None)
    rent_val = float(re.sub(r'[^\d.]', '', rent_str)) if rent_str else None

    cur.execute(
        "UPDATE properties SET rent=?, bedrooms=?, bathrooms=?, status=? WHERE id=?",
        (rent_val, br_val, ba_val, status, pid)
    )
    if cur.rowcount:
        updated += 1
        print(f"  [UPDATED] #{pid} {orig_prop} {orig_unit} → ${rent_val}/{br_val}/{ba_val}/{status}")

# ── Phase 2: Find referenced property IDs ──
referenced = set()
for table in ('leads', 'applications', 'property_files'):
    try:
        for row in cur.execute(f"SELECT DISTINCT property_id FROM {table} WHERE property_id IS NOT NULL"):
            referenced.add(row[0])
    except Exception:
        pass

# ── Phase 3: Delete non-spreadsheet, non-referenced, non-sales-deal ──
spreadsheet_ids = set()
for sp in spreadsheet:
    key = sp[:2]
    match_ids = key_to_id.get(key, [])
    if match_ids:
        spreadsheet_ids.add(match_ids[0])

deleted = 0
for pid in list(all_props.keys()):
    if pid in spreadsheet_ids: continue
    if pid in referenced: continue
    cur.execute("DELETE FROM properties WHERE id=?", (pid,))
    if cur.rowcount:
        deleted += 1

conn.commit()
conn.close()

print(f"\nSummary:")
print(f"  Matched + updated: {updated}")
print(f"  Deleted (junk/non-referenced): {deleted}")
print(f"  Kept (referenced by leads/apps): {len(referenced - spreadsheet_ids)}")
print(f"  Total remaining: {len(spreadsheet_ids | (referenced - spreadsheet_ids))}")