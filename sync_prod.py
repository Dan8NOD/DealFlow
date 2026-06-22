"""One-shot prod cleanup: dedup + sync spreadsheet values to Render API."""
import requests, openpyxl, re, os
from urllib.parse import urljoin

BASE = "https://renter-portal-1-jajv.onrender.com"
S = requests.Session()

def login():
    r = S.post(f"{BASE}/auth/login", data={"email": "dancruzhomes@gmail.com", "password": "Leads2025!"})
    r.raise_for_status()
    return r

def dedup():
    r = S.post(f"{BASE}/api/properties/dedup")
    r.raise_for_status()
    return r.json()

def norm(a):
    if not a: return ""
    a = a.lower().strip()
    a = re.sub(r'\.', '', a)
    a = re.sub(r'\b(street|st|avenue|ave|boulevard|blvd|road|rd|drive|dr|lane|ln|court|ct)\b', '', a)
    a = re.sub(r'\b(south|north|east|west|n|s|e|w)\b', '', a)
    a = re.sub(r'[,;:]', '', a)
    a = re.sub(r'\s+', ' ', a).strip()
    m = re.match(r'(\d+)\s+(\w+)', a)
    return f"{m.group(1)} {m.group(2)}"[:30] if m else a[:30]

def norm_unit(u):
    return re.sub(r'\s+', '', str(u).lower().replace('.', '')) if u else ""

def parse_br_ba(s):
    """'2BR' -> 2, '1.5BA' -> 1.5"""
    if not s: return None
    s = str(s).upper()
    m = re.search(r'([\d.]+)\s*B[RA]', s)
    return float(m.group(1)) if m else None

# ── Login ──
print("Login...")
login()

# ── Phase 1: Dedup ──
print("\nDedup...")
d = dedup()
print(f"  Merged: {d.get('merged_groups',0)} groups, deleted: {d.get('deleted_duplicates',0)}, leads reassigned: {d.get('leads_reassigned',0)}, remaining: {d.get('remaining_properties',0)}")

# ── Phase 2: Fetch property list from prod ──
print("\nFetching prod properties...")
r = S.get(f"{BASE}/api/properties?limit=500")
r.raise_for_status()
prod_props = r.json()

# Build key → id index
key_to_id = {}
for p in prod_props:
    k = (norm(p['address']), norm_unit(p['unit']))
    key_to_id.setdefault(k, []).append(p['id'])

# ── Phase 3: Read spreadsheet ──
xlsx = os.path.expanduser("~/Desktop/Active_Leads/renter_leads_calling_v5_20260619.xlsx")
wb = openpyxl.load_workbook(xlsx, data_only=True)
ws = wb['Property Master']

updates = []
for row in ws.iter_rows(min_row=2, values_only=True):
    prop, unit, br, ba, rent, status, *_ = [str(v) if v is not None else '' for v in row]
    key = (norm(prop), norm_unit(unit))
    match_ids = key_to_id.get(key, [])
    if not match_ids:
        continue
    pid = match_ids[0]
    body = {}
    if status and status.strip():
        body['status'] = status.strip()
    if rent and rent.strip():
        try: body['rent'] = float(re.sub(r'[^\d.]', '', rent))
        except: pass
    br_val = parse_br_ba(br)
    if br_val: body['bedrooms'] = br_val
    ba_val = parse_br_ba(ba)
    if ba_val: body['bathrooms'] = ba_val
    if body:
        updates.append((pid, body))

# ── Phase 4: PATCH each property ──
print(f"\nPatching {len(updates)} properties...")
ok = 0
for pid, body in updates:
    try:
        r = S.patch(f"{BASE}/api/properties/{pid}", json=body)
        if r.ok: ok += 1
        else: print(f"  FAIL #{pid}: {r.status_code}")
    except Exception as e:
        print(f"  ERROR #{pid}: {e}")

print(f"\nDone. Updated: {ok}/{len(updates)}")