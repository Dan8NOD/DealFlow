"""
sync_obsidian.py — Parse Obsidian LEASING notes and sync structured property data into renter_portal.db.

Extracts: address, unit, bed/bath, rent, available date, pet restrictions,
utilities, parking, storage, laundry, asset manager, lockbox codes, MLS IDs,
CMA links, listing descriptions, showing instructions, current tenants.

Usage:  python3 scripts/sync_obsidian.py
"""

import re
import sys
from pathlib import Path
from datetime import datetime

OBSIDIAN_VAULT    = Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "Real Estate"
LEASING_DIR       = OBSIDIAN_VAULT / "Real Estate" / "LEASING"
DB_PATH           = Path(__file__).parent.parent / "renter_portal.db"

SKIP_ADDRESSES = {
    "sellers", "buyers", "closed", "july", "march", "april", "may", "june",
    "january", "february", "august", "september", "october", "november", "december",
    "address", "unit", "sales", "referral fee %20  with zach", "",
}


def norm(s):
    if not s:
        return ""
    return re.sub(r'\s+', ' ', str(s).strip()).lower()


def find_note_for_property(address, unit=""):
    """Find the Obsidian LEASING note that best matches a property address."""
    if not address:
        return None
    an = norm(address)
    un = norm(unit)
    if not LEASING_DIR.exists():
        return None
    best = None
    best_score = 0
    for fpath in sorted(LEASING_DIR.glob("*.md")):
        text = fpath.read_text(encoding="utf-8", errors="replace")
        tn = norm(text[:500])
        score = 0
        if an in tn or tn.find(an) >= 0:
            score += 5
        # Check filename
        fn = norm(fpath.stem)
        if an in fn:
            score += 3
        # Check unit match
        if un and un in tn:
            score += 2
        if score > best_score:
            best_score = score
            best = (fpath, text)
    if best and best_score >= 3:
        return best
    return None


def parse_field(text, label, end_marker=None, greedy=False):
    """Extract the value for a bold-markdown field like **Address:** or **Pet Restrictions:**"""
    patterns = [
        rf'\*\*{re.escape(label)}:\*\*\s*(.*?)(?:\n\s*\n|\n---|\n\s*\*\*|\Z)',
        rf'\*\*{re.escape(label)}[:\s]+\*\*\s*(.*?)(?:\n\s*\n|\n---|\n\s*\*\*|\Z)',
        rf'{re.escape(label)}:\s*(.*?)(?:\n\s*\n|\n---|\n\s*\*\*|\Z)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            val = m.group(1).strip()
            # Strip trailing markdown or pipes
            val = re.sub(r'\s*\n[\|\s]*\n.*', '', val, flags=re.DOTALL)
            val = val.split('\n')[0].strip()
            val = re.sub(r'\s+', ' ', val)
            return val
    return None


def parse_listing_description(text):
    """Attempt to find the marketing description paragraph."""
    # Look for heading "## Listing Description" or similar
    m = re.search(r'## (?:Listing Description|Marketing Description|Property Description)\s*\n(.*?)(?:\n##|\n---|\Z)', text, re.DOTALL)
    if m:
        desc = m.group(1).strip()
        # Truncate at reasonable length
        if len(desc) > 800:
            desc = desc[:800] + "..."
        return desc
    return None


def parse_lockbox_code(text):
    """Extract lockbox codes — pattern: 'lockbox code: 1234' or 'code 7819' etc."""
    codes = []
    # Lockbox code patterns
    for m in re.finditer(r'(?:lockbox|lock.?box|key.?box)\s*(?:code|number|combo)?[:\s]*(\d{3,6})', text, re.IGNORECASE):
        codes.append(m.group(1))
    for m in re.finditer(r'code[:\s]+(\d{3,6})', text[:1000], re.IGNORECASE):
        if m.group(1) not in codes:
            codes.append(m.group(1))
    return "; ".join(codes[:4]) if codes else None


def parse_mls_id(text):
    """Extract MLS ID(s) — patterns like MLS# 12650530 or MLS ID: 12650530"""
    ids = []
    for m in re.finditer(r'(?:MLS[#:\s]*|listing\s*ID[#:\s]*)\s*(\d{6,10})', text, re.IGNORECASE):
        ids.append(m.group(1))
    return "; ".join(ids[:3]) if ids else None


def parse_tenant_info(text):
    """Extract current tenant name, phone, email if present in table form."""
    tenant = {}
    # Try table rows with Primary/Other
    m = re.search(r'Primary[^|]*\|[^|]*\[([^\]]+)\]\([^)]+\)[^|]*\|[^|]*\|[^|]*\|[^|]*\|[^|]*\|[^|]*\|[^|]*\(?(\d{3})[^)]*\)?\s*(\d{3})[-\s.]*(\d{4})', text)
    if m:
        tenant['name'] = m.group(1).strip()
        tenant['phone'] = f"({m.group(2)}) {m.group(3)}-{m.group(4)}"
    # Also parse inline tenant info
    if not tenant:
        m = re.search(r'Primary Tenant[:\s]*(.*?)(?:\n|$)', text)
        if m:
            tenant['name'] = m.group(1).strip()
    return tenant


def parse_available_date(text):
    """Parse available date string."""
    m = re.search(r'Date Available[:\s]*(.*?)(?:\n|$)', text)
    if m:
        date_str = m.group(1).strip().strip('*')
        # Try various date formats
        for fmt in ['%m/%d/%Y', '%Y-%m-%d', '%B %d, %Y', '%m-%d-%Y']:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
    # Also try "Available:" pattern
    m = re.search(r'\*\*Available:\*\*\s*(.*?)(?:\n|$)', text)
    if m:
        date_str = m.group(1).strip()
        for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%B %d, %Y']:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
    # Also try 'ASAP' or similar
    m = re.search(r'\*\*Date Available:\*\*\s*(.*?)(?:\n|$)', text)
    if m:
        val = m.group(1).strip().strip('*')
        if val.upper() in ("ASAP", "IMMEDIATE", "NOW", ""):
            return None
        for fmt in ['%m/%d/%Y', '%Y-%m-%d', '%B %d, %Y', '%m-%d-%Y']:
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
    return None


def parse_rent(text):
    """Extract rent amount."""
    for pat in [
        r'Current rental rate:\s*\$?([\d,]+(?:\.\d{2})?)',
        r'Rental Amount:\s*\$?([\d,]+(?:\.\d{2})?)',
        r'Current Rental Rate:\s*\$?([\d,]+(?:\.\d{2})?)',
        r'\*\*Rental Amount:\*\*[^$]*\$?([\d,]+(?:\.\d{2})?)',
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return float(m.group(1).replace(',', ''))
    return None


def parse_suggested_rent(text):
    """Extract suggested rental rate from CMA section."""
    m = re.search(r'Suggested (?:Rental|List)(?:ing)?\s*(?:Price|Rate)?[:\s]*\$?([\d,]+(?:\.\d{2})?)', text)
    if m:
        return float(m.group(1).replace(',', ''))
    m = re.search(r'Suggested\s*list\s*price[:\s]*\$?([\d,]+)', text, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(',', ''))
    return None


def parse_cma_link(text):
    """Extract CloudCMA link."""
    m = re.search(r'(https?://cloudcma\.com/pdf/[^\s)]+)', text)
    if m:
        return m.group(1)
    return None


def parse_utilities(text):
    """Extract utilities included / paid by tenant."""
    included = []
    paid_by_tenant = []
    # Check for the standard fields
    inc_raw = parse_field(text, "Utilities Paid by Tenant")
    if inc_raw:
        paid_by_tenant.append(inc_raw)
    else:
        m = re.search(r'Utilities paid by tenant[:\s]*(.*?)(?:\n|$)', text, re.IGNORECASE)
        if m:
            paid_by_tenant.append(m.group(1).strip())

    # Check Included in Rent / utilities included
    inc2 = parse_field(text, "Included in Rent")
    if inc2:
        included.append(inc2)
    m = re.search(r'Utilities included[:\s]*(.*?)(?:\n|$)', text, re.IGNORECASE)
    if m:
        included.append(m.group(1).strip())
    # Parse bullet list of utilities
    if not included:
        bullet_section = re.search(r'Utilities included:[\s\n]*([^#]*?)(?:\n\n|\n#|\Z)', text, re.IGNORECASE | re.DOTALL)
        if bullet_section:
            bullets = re.findall(r'[-*]\s*(.+?)$', bullet_section.group(1), re.MULTILINE)
            if bullets:
                included = bullets

    return "; ".join(included) if included else None, "; ".join(paid_by_tenant) if paid_by_tenant else None


def parse_showing_instructions(text):
    """Extract showing instructions."""
    # Look for ShowingTime mentions
    if 'showingtime' in text.lower():
        return "Use ShowingTime for scheduling"
    m = re.search(r'Showing Instructions[:\s]*(.*?)(?:\n|$)', text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def extract_property_data(filepath, full_text):
    """Extract all structured property data from an Obsidian note."""
    data = {}

    # Address
    addr = parse_field(full_text, "Address")
    if not addr:
        addr = parse_field(full_text, "property address")
    if not addr:
        # Try filename-based extraction
        stem = filepath.stem
        # Remove prefix like "9@SHOW " or "1@SHOW "
        clean = re.sub(r'^[\d]+@\w+\s+', '', stem)
        if clean:
            addr = clean
    data['address'] = addr

    # Unit
    unit = parse_field(full_text, "Unit")
    data['unit'] = unit or ""

    # Bed/Bath
    bed_bath = parse_field(full_text, "Bed/Bath") or parse_field(full_text, "Layout")
    if bed_bath:
        m = re.match(r'(\d+)\s*(?:Bed|BR)[/\s]+(\d+)\s*(?:Bath|BA)', bed_bath, re.IGNORECASE)
        if m:
            data['bedrooms'] = float(m.group(1))
            data['bathrooms'] = float(m.group(2))
        else:
            m = re.match(r'(\d+)\s*[Bb]ed', bed_bath)
            if m:
                data['bedrooms'] = float(m.group(1))

    # Rent
    rent = parse_rent(full_text)
    if rent:
        data['rent'] = rent

    # Suggested rent (from CMA)
    suggested = parse_suggested_rent(full_text)
    if suggested:
        data['suggested_rent'] = suggested

    # Available date
    avail = parse_available_date(full_text)
    if avail:
        data['available_date'] = avail

    # Pet restrictions
    pets = parse_field(full_text, "Pet Restrictions")
    if not pets:
        pets = parse_field(full_text, "pets")
    data['pet_restrictions'] = pets

    # Utilities
    inc, by_tenant = parse_utilities(full_text)
    data['utilities_included'] = inc
    data['utilities_paid_by_tenant'] = by_tenant

    # Parking
    parking = parse_field(full_text, "Parking")
    data['parking'] = parking

    # Storage
    storage = parse_field(full_text, "Storage")
    data['storage'] = storage

    # Laundry
    laundry = parse_field(full_text, "Laundry")
    data['laundry'] = laundry

    # Asset Manager
    am = parse_field(full_text, "Asset Manager")
    data['asset_manager'] = am

    # Lockbox
    data['lockbox_code'] = parse_lockbox_code(full_text)

    # MLS ID
    data['mls_id'] = parse_mls_id(full_text)

    # CMA Link
    data['cma_link'] = parse_cma_link(full_text)

    # Listing description
    data['listing_description'] = parse_listing_description(full_text)

    # Showing instructions
    data['showing_instructions'] = parse_showing_instructions(full_text)

    # Tenant info
    tenant = parse_tenant_info(full_text)
    data['tenant_name'] = tenant.get('name', '')

    return data


def main():
    if not LEASING_DIR.exists():
        print(f"ERROR: LEASING dir not found at {LEASING_DIR}")
        sys.exit(1)

    import sqlite3
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()

    # Get org_id
    cur.execute("SELECT id FROM organizations LIMIT 1")
    row = cur.fetchone()
    if not row:
        print("ERROR: No organization found in DB.")
        sys.exit(1)
    org_id = row[0]

    # Fetch all properties
    cur.execute("SELECT id, address, unit FROM properties WHERE org_id=?", (org_id,))
    properties = cur.fetchall()
    print(f"Syncing {len(properties)} properties from {len(list(LEASING_DIR.glob('*.md')))} Obsidian notes...")

    new_lease_added = 0
    updated_with_obsidian = 0
    notes_without_property = 0

    # Track which properties we updated
    updated_ids = set()

    # Map property addresses to Obsidian notes
    for pid, address, unit in properties:
        result = find_note_for_property(address, unit)
        if not result:
            continue
        fpath, text = result
        data = extract_property_data(fpath, text)
        if not data.get('address'):
            continue

        updates = []
        params = []

        # Map fields to DB columns
        field_map = {
            'pet_restrictions': 'pet_restrictions',
            'utilities_included': 'utilities_included',
            'utilities_paid_by_tenant': 'utilities_paid_by_tenant',
            'parking': 'parking',
            'storage': 'storage',
            'laundry': 'laundry',
            'asset_manager': 'asset_manager',
            'lockbox_code': 'lockbox_code',
            'mls_id': 'mls_id',
            'cma_link': 'cma_link',
            'listing_description': 'listing_description',
            'showing_instructions': 'showing_instructions',
            'tenant_name': 'tenant_name',
            'rent': 'rent',
            'bedrooms': 'bedrooms',
            'bathrooms': 'bathrooms',
        }

        for src, dst in field_map.items():
            val = data.get(src)
            if val is not None and val != "":
                updates.append(f'"{dst}"=?')
                params.append(val)

        # available_date separately
        if data.get('available_date'):
            updates.append('"available_date"=?')
            params.append(data['available_date'].isoformat())

        if updates:
            params.append(pid)
            sql = f'UPDATE properties SET {", ".join(updates)} WHERE id=?'
            try:
                cur.execute(sql, params)
                if cur.rowcount > 0:
                    updated_ids.add(pid)
                    updated_with_obsidian += 1
            except Exception as e:
                print(f"  DB error for property #{pid} ({address}): {e}")

    # Check for notes not matched to any property
    note_count = 0
    for fpath in sorted(LEASING_DIR.glob("*.md")):
        text = fpath.read_text(encoding="utf-8", errors="replace")
        addr_from_note = extract_property_data(fpath, text).get('address', '')
        note_count += 1
        if addr_from_note:
            a = norm(addr_from_note)
            cur.execute(
                "SELECT COUNT(*) FROM properties WHERE org_id=? AND lower(trim(address)) LIKE ?",
                (org_id, f'%{a.split(",")[0].strip()[:15]}%')
            )
            if cur.fetchone()[0] == 0:
                notes_without_property += 1

    con.commit()
    con.close()

    print(f"\n=== OBSIDIAN SYNC COMPLETE ===")
    print(f"  Notes parsed         : {note_count}")
    print(f"  Properties matched   : {updated_with_obsidian}")
    print(f"  Notes no match       : {notes_without_property}")
    print(f"  New enriched entries  : {len(updated_ids)}")
    if notes_without_property:
        print(f"  ⚠  {notes_without_property} Obsidian notes had no matching property in DB —")
        print(f"     review and add these properties or fix address matching")


if __name__ == "__main__":
    main()
