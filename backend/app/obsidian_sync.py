"""
Obsidian vault sync engine — bidirectional bridge between Obsidian notes and the Renter Portal DB.

Conventions:
- LEASING notes: `@@STATUS Address.md` where STATUS = SHOW, POST, CMA, PayMEApproved, Paid, PAYOUT, EVICT, CONSTRUCT, Waiting, ISRAEL
- SALES notes: `@@STATUS Address.md`
- Status prefixes: stripped for address matching, preserved as metadata
- Notes may have structured sections: Property Overview, Tenant, Applicant, Marketing, etc.
"""
import os
import re
import sqlite3
import json
import hashlib
from typing import Optional
from datetime import datetime, timezone
from pathlib import Path

# Obsidian vault paths
VAULT_PATHS = [
    os.path.expanduser("~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Real Estate/Real Estate"),
    os.path.expanduser("~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Nod News"),
]

# Status prefix patterns: number then @STATUS
STATUS_RE = re.compile(r'^(\d+)\s*@\s*(\w+)', re.IGNORECASE)
# Address patterns extracted from filenames
ADDR_RE = re.compile(r'(\d+)\s+[NSEW]\s+[\w\s]+', re.IGNORECASE)

# Valid sections: LEASING, SALES
SECTION_MAP = {"LEASING": "leasing", "SALES": "sales"}

# Status mapping: Obsidian prefix → portal status
STATUS_MAP = {
    "SHOW": "SHOWING",
    "POST": "POSTED",
    "CMA": "CMA_REQUESTED",
    "PayMEApproved": "RENTED",
    "Paid": "RENTED",
    "PAYOUT": "RENTED",
    "EVICT": "EVICTION",
    "CONSTRUCT": "CONSTRUCTION",
    "CONSTRUC": "CONSTRUCTION",
    "Waiting": "PENDING",
    "ISRAEL": "ASSIGNED",
}


def normalize_address(addr: str) -> str:
    """Normalize address for fuzzy matching."""
    addr = addr.strip()
    # Remove status prefix
    addr = STATUS_RE.sub("", addr)
    # Remove .md extension
    addr = addr.replace(".md", "")
    # Remove leading/trailing special chars
    addr = addr.strip(" *")
    # Lowercase
    addr = addr.lower()
    # Normalize directionals
    addr = re.sub(r'\bn\.?\b', 'n', addr)
    addr = re.sub(r'\bs\.?\b', 's', addr)
    addr = re.sub(r'\be\.?\b', 'e', addr)
    addr = re.sub(r'\bw\.?\b', 'w', addr)
    # Normalize street suffixes
    addr = re.sub(r'\bst\.?\b', 'st', addr)
    addr = re.sub(r'\bave\.?\b', 'ave', addr)
    addr = re.sub(r'\bblvd\.?\b', 'blvd', addr)
    addr = re.sub(r'\brd\.?\b', 'rd', addr)
    addr = re.sub(r'\bdr\.?\b', 'dr', addr)
    addr = re.sub(r'\bct\.?\b', 'ct', addr)
    addr = re.sub(r'\bpl\.?\b', 'pl', addr)
    addr = re.sub(r'\bter\.?\b', 'ter', addr)
    # Remove unit suffixes from address portion
    addr = re.sub(r'\b(apt|unit|#)\s*\w+\b', '', addr)
    addr = re.sub(r'\b\d+[a-z]?\s*(th|nd|rd|st)\b', '', addr, flags=re.IGNORECASE)
    # Collapse spaces
    addr = re.sub(r'\s+', ' ', addr).strip()
    # Remove trailing city/state/zip
    addr = re.sub(r'\s+(chicago|riverdale|calumet|homewood|joliet|downers\s*grove|oak\s*lawn)[\s,]+il\s*\d*$', '', addr)
    return addr


def extract_address_key(addr: str) -> str:
    """Extract numeric street address and street name for matching."""
    addr = normalize_address(addr)
    # Get street number + first word of street name
    m = re.match(r'(\d+)\s+([nsew]\s+)?(\w+)', addr)
    if m:
        num = m.group(1)
        street = m.group(3) if m.group(3) else ""
        return f"{num} {street}"
    return addr[:30]


def parse_obsidian_note(filepath: str) -> dict:
    """Parse an Obsidian note and extract structured data."""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
    except Exception:
        return None

    filename = os.path.basename(filepath)
    fname_no_ext = filename.replace(".md", "")

    # Extract status prefix
    status_match = STATUS_RE.match(fname_no_ext)
    status_prefix = status_match.group(2) if status_match else ""
    priority = int(status_match.group(1)) if status_match else 0

    # Parse sections
    sections = {}
    current_section = "_header"
    sections[current_section] = []

    for line in content.split('\n'):
        if line.startswith('## '):
            current_section = line[3:].strip()
            if current_section not in sections:
                sections[current_section] = []
        else:
            sections[current_section].append(line)

    # Extract key fields
    data = {
        "filepath": filepath,
        "filename": filename,
        "status_prefix": status_prefix,
        "priority": priority,
        "portal_status": STATUS_MAP.get(status_prefix, ""),
        "section": "LEASING" if "/LEASING/" in filepath else "SALES",
        "content_hash": hashlib.md5(content.encode()).hexdigest(),
        "lines": len(content.split('\n')),
        "size": len(content),
        "modified": datetime.fromtimestamp(os.path.getmtime(filepath), tz=timezone.utc).isoformat(),
    }

    # Extract address from title line or filename
    title_line = sections.get("_header", [""])[0] if sections.get("_header") else ""
    data["raw_address"] = normalize_address(fname_no_ext)

    # Property Overview section
    overview = "\n".join(sections.get("Property Overview", []))
    m = re.search(r'\*\*Address:\*\*\s*(.+)', overview)
    if m:
        data["clean_address"] = m.group(1).strip()
    m = re.search(r'\*\*Bed/Bath:\*\*\s*(.+)', overview)
    if m:
        bb = m.group(1).strip()
        parts = bb.split('/')
        if len(parts) == 2:
            try:
                data["bedrooms"] = int(parts[0].strip().split()[0])
                data["bathrooms"] = float(parts[1].strip().split()[0])
            except ValueError:
                pass
    m = re.search(r'\*\*Status:\*\*\s*(.+)', overview)
    if m:
        data["unit_status"] = m.group(1).strip()

    # Tenant section
    tenant_section = "\n".join(sections.get("Current Tenant Record", []))
    m = re.search(r'\*\*Tenant:\*\*\s*(.+)', tenant_section)
    if m:
        data["tenant_name"] = m.group(1).strip()
    m = re.search(r'\*\*Rent:\*\*\s*\$?([\d,]+)', tenant_section)
    if m:
        data["rent"] = float(m.group(1).replace(",", ""))

    # Applicant section
    applicant_section = "\n".join(sections.get("Recent Applicant", []))
    m = re.search(r'\*\*Applicant:\*\*\s*(.+)', applicant_section)
    if m:
        data["applicant_name"] = m.group(1).strip()

    # Pricing
    for line in content.split('\n'):
        m = re.search(r'\|\s*\$?([\d,]+\.?\d*)\s*\|', line)
        if m and not data.get("rent"):
            try:
                data["rent"] = float(m.group(1).replace(",", ""))
            except ValueError:
                pass
            break

    # CMA link
    m = re.search(r'(https://cloudcma\.com/\S+)', content)
    if m:
        data["cma_url"] = m.group(1)

    # ShowMojo link
    m = re.search(r'(https?://showmojo\.com/\S+)', content)
    if m:
        data["showmojo_url"] = m.group(1).rstrip(')')

    # MLS number
    m = re.search(r'MLS[#\s:]*(\d{7,8})', content)
    if m:
        data["mls_number"] = m.group(1)

    return data


def scan_all_vaults() -> list:
    """Scan all Obsidian vaults for property notes and return parsed data."""
    results = []
    for vault in VAULT_PATHS:
        if not os.path.isdir(vault):
            continue
        for section_dir in ["LEASING", "SALES"]:
            section_path = os.path.join(vault, section_dir)
            if not os.path.isdir(section_path):
                continue
            for fname in os.listdir(section_path):
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(section_path, fname)
                parsed = parse_obsidian_note(fpath)
                if parsed:
                    parsed["vault"] = os.path.basename(vault)
                    results.append(parsed)
    return results


def find_matching_property(note_data: dict, db_path: str) -> Optional[dict]:
    """Match an Obsidian note to a property in the SQLite DB using fuzzy matching."""
    conn = sqlite3.connect(db_path)
    cur = conn.execute("SELECT id, address, unit FROM properties WHERE org_id = 1")
    properties = cur.fetchall()
    conn.close()

    note_addr = note_data.get("raw_address", "")
    note_key = extract_address_key(note_addr)

    best_match = None
    best_score = 0

    for prop_id, prop_addr, prop_unit in properties:
        prop_key = extract_address_key(prop_addr)
        if not prop_key or not note_key:
            continue

        # Exact match on address key (number + first street word)
        if prop_key == note_key:
            score = 80
            # Bonus for unit match
            if prop_unit and prop_unit.lower() in note_addr.lower():
                score = 100
            if score > best_score:
                best_score = score
                best_match = {"id": prop_id, "address": prop_addr, "unit": prop_unit}

        # Partial match (same street number)
        elif prop_key.split()[0] == note_key.split()[0]:
            score = 50
            if note_key.split()[-1] in prop_key:
                score = 70
            if score > best_score:
                best_score = score
                best_match = {"id": prop_id, "address": prop_addr, "unit": prop_unit}

    return best_match


def sync_to_db(data: list, db_path: str) -> dict:
    """Sync parsed Obsidian data to the property_files table and update property statuses."""
    conn = sqlite3.connect(db_path)
    stats = {"matched": 0, "unmatched": 0, "updated": 0, "new_files": 0}

    for note in data:
        match = find_matching_property(note, db_path)
        if match:
            stats["matched"] += 1
            prop_id = match["id"]

            # Check if this obsidian file is already tracked
            cur = conn.execute(
                "SELECT id FROM property_files WHERE path = ? AND source = 'obsidian'",
                (note["filepath"],)
            )
            existing = cur.fetchone()

            if existing:
                conn.execute(
                    """UPDATE property_files SET
                        name = ?, kind = ?, section = ?, obsidian_vault = ?,
                        size_bytes = ?
                    WHERE id = ?""",
                    (note["filename"], note["portal_status"] or "NOTE",
                     note["section"], note["vault"],
                     note["size"], existing[0])
                )
                stats["updated"] += 1
            else:
                conn.execute(
                    """INSERT INTO property_files
                    (org_id, property_id, kind, name, path, source, obsidian_vault, section, size_bytes)
                    VALUES (1, ?, ?, ?, ?, 'obsidian', ?, ?, ?)""",
                    (prop_id, note["portal_status"] or "NOTE",
                     note["filename"], note["filepath"],
                     note["vault"], note["section"], note["size"])
                )
                stats["new_files"] += 1

            # Update property status from Obsidian if the property is currently AVAILABLE
            if note.get("portal_status"):
                cur2 = conn.execute(
                    "SELECT status FROM properties WHERE id = ?", (prop_id,)
                )
                row = cur2.fetchone()
                if row and row[0] == "AVAILABLE":
                    portal_status = note["portal_status"]
                    if portal_status == "RENTED":
                        conn.execute(
                            "UPDATE properties SET status = 'RENTED' WHERE id = ?",
                            (prop_id,)
                        )

            # Update property details if available
            if note.get("tenant_name"):
                conn.execute(
                    "UPDATE properties SET tenant_name = ? WHERE id = ? AND tenant_name IS NULL",
                    (note["tenant_name"], prop_id)
                )
            if note.get("bedrooms"):
                conn.execute(
                    "UPDATE properties SET bedrooms = ? WHERE id = ? AND bedrooms IS NULL",
                    (note["bedrooms"], prop_id)
                )
            if note.get("bathrooms"):
                conn.execute(
                    "UPDATE properties SET bathrooms = ? WHERE id = ? AND bathrooms IS NULL",
                    (note["bathrooms"], prop_id)
                )
            if note.get("rent") and note["rent"] > 0:
                conn.execute(
                    "UPDATE properties SET rent = ? WHERE id = ? AND (rent IS NULL OR rent = 0)",
                    (note["rent"], prop_id)
                )
        else:
            stats["unmatched"] += 1

    conn.commit()
    conn.close()
    return stats


def update_obsidian_note(property_data: dict, db_path: str) -> bool:
    """Push a portal change back to an Obsidian note (status update)."""
    # Find the note path from property_files
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "SELECT path FROM property_files WHERE property_id = ? AND source = 'obsidian' LIMIT 1",
        (property_data.get("id"),)
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return False

    note_path = row[0]
    if not os.path.exists(note_path):
        return False

    try:
        with open(note_path, 'r') as f:
            content = f.read()

        # Update status line in header
        new_status = property_data.get("portal_status", "")
        if new_status:
            # Find the first header line with status-like content
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if '**Status:' in line or '**Status**' in line:
                    break

        # Touch the file to update modtime
        os.utime(note_path, None)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    # Standalone: scan and print results
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else "renter_portal.db"
    results = scan_all_vaults()
    print(f"Found {len(results)} Obsidian notes")

    if os.path.exists(db):
        stats = sync_to_db(results, db)
        print(f"Synced: {stats}")
    else:
        print(f"DB not found at {db}, printing raw scan:")
        for r in results:
            print(f"  [{r['section']}] {r['status_prefix']} — {r['raw_address'][:60]}")