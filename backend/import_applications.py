#!/usr/bin/env python3
"""Load applications_extracted.json into renter_portal.db.

Merges by applicant_name:
- If applicant already exists -> skip (don't duplicate)
- If not -> insert + create one application_received event
- Detects "move-in ready" apps (status=move_in_ready) -> set status to MOVED_IN

Run:
  cd backend
  .venv/bin/python import_applications.py

Source: /Users/danielcruz/Desktop/Leads/applications_extracted.json
"""
import sys
import json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from app.db import SessionLocal
from app.models import (
    Application, ApplicationEvent, Property, ApplicationStatus,
)
from sqlalchemy import func

APPS_JSON = Path("/Users/danielcruz/Desktop/Leads/applications_extracted.json")

# Garbled / non-applicant subjects to skip
GARBLED = [
    "offer 2 of 2", "or any unit", "or any similar",
    "warrant application", "approved at", "1465 e 69th st unit 1c",
]

# Status mapping from extracted JSON -> SQLAlchemy enum
STATUS_MAP = {
    "submitted": ApplicationStatus.APPLICATION_RECEIVED,
    "reviewing": ApplicationStatus.APPLICATION_RECEIVED,
    "pending":   ApplicationStatus.OFFER_SENT,
    "move_in_ready": ApplicationStatus.MOVED_IN,
}


def load_applications():
    if not APPS_JSON.exists():
        print(f"ERROR: {APPS_JSON} not found")
        return

    raw = json.loads(APPS_JSON.read_text())
    print(f"Source: {len(raw)} raw entries")

    # Filter out garbled names
    entries = []
    for a in raw:
        name = a.get("applicant", "").strip()
        if len(name) <= 4 or name.lower() in [g.lower() for g in GARBLED]:
            continue
        entries.append(a)
    print(f"After filtering garbled names: {len(entries)} entries")

    db = SessionLocal()

    # Property address lookup (normalized)
    props = db.query(Property).filter(Property.org_id == 1).all()
    addr_map = {}
    for p in props:
        key = (p.address or "").lower().replace(".", "").replace(",", "").strip()
        addr_map[key] = p

    inserted = 0
    skipped_dup = 0
    matched_prop = 0

    for a in entries:
        name = a["applicant"]
        # Handle both date-only and datetime formats
        sub_str = a["submitted"].split()[0]  # strip time if present
        upd_str = a["last_update"].split()[0]
        submitted = datetime.strptime(sub_str, "%Y-%m-%d")
        last_update = datetime.strptime(upd_str, "%Y-%m-%d")
        days = (datetime.now() - submitted).days
        status = STATUS_MAP.get(a.get("status", ""), ApplicationStatus.APPLICATION_RECEIVED)

        # Skip if applicant already exists
        if db.query(Application).filter(
            Application.org_id == 1,
            Application.applicant_name == name,
        ).first():
            skipped_dup += 1
            continue

        # Try to match a property
        addr = a["property"].lower().replace(".", "").replace(",", "").strip()
        prop = None
        for key, p in addr_map.items():
            if addr.startswith(key) or key.startswith(addr):
                prop = p
                break
            # Try just the street part
            addr_street = addr.split(" unit")[0].split(" apt")[0]
            key_street = key.split(" unit")[0].split(" apt")[0]
            if addr_street == key_street:
                prop = p
                break

        app = Application(
            org_id=1,
            property_id=prop.id if prop else None,
            applicant_name=name,
            unit=a.get("unit", "") or (prop.unit if prop else ""),
            status=status,
            handler=a.get("sender", ""),
            first_seen=submitted,
            last_update=last_update,
            days_in_pipeline=days,
            event_count=a.get("email_count", 1),
        )
        db.add(app)
        db.flush()

        # Create one event
        evt = ApplicationEvent(
            application_id=app.id,
            event_type="application_received",
            occurred_at=submitted,
            handler=a.get("sender", ""),
            subject=f"Imported: {a['property']}",
        )
        db.add(evt)

        if prop:
            matched_prop += 1
        inserted += 1

    db.commit()

    total = db.query(Application).filter(Application.org_id == 1).count()
    status_counts = db.query(
        Application.status, func.count(Application.id)
    ).filter(Application.org_id == 1).group_by(Application.status).all()

    db.close()

    print(f"\n=== RESULT ===")
    print(f"Inserted:       {inserted}")
    print(f"Skipped (dup):  {skipped_dup}")
    print(f"Matched property: {matched_prop}")
    print(f"Total in DB:    {total}")
    print(f"\nStatus breakdown:")
    for s, c in sorted(status_counts, key=lambda x: -x[1]):
        print(f"  {s.value:25s}  {c}")


if __name__ == "__main__":
    load_applications()
