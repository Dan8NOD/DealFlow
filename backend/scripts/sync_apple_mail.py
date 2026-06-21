#!/usr/bin/env python3
"""
sync_apple_mail.py — Scan local Apple Mail and push real-estate-related messages
into the Renter Portal SaaS DB.

Usage:
    cd /Users/danielcruz/Desktop/Leads/saas/backend
    python3 scripts/sync_apple_mail.py

Environment:
    DATABASE_URL — defaults to sqlite:///./renter_portal.db
    HOURS_BACK   — how far back to scan (default 24)
    LIMIT        — max messages to scan (default 500)

Designed to be cron'd, e.g. every hour:
    0 * * * * cd /Users/danielcruz/Desktop/Leads/saas/backend && /usr/bin/python3 scripts/sync_apple_mail.py >> /tmp/apple_mail_sync.log 2>&1
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal
from app.models import EmailMessage, Organization
from app.integrations.apple_mail import list_recent_messages
from app.integrations.sync_engine import (
    _create_or_update_lead,
    _create_or_update_application,
    _create_or_update_sales_deal,
    _create_or_update_cma,
    find_property,
)


def parsed_from_msg(msg: dict) -> dict:
    return {
        "external_id": msg["external_id"],
        "subject": msg["subject"],
        "sender_email": msg["sender_email"],
        "sender_name": msg["sender_name"],
        "received_at": msg["received_at"].isoformat() if msg["received_at"] else None,
        "body_preview": msg["body_preview"],
    }


def classify_to_dict(msg: dict) -> dict:
    return {
        "event_type": msg["event_type"],
        "property_address": msg["property_address"],
        "unit": msg["unit"],
        "handler": msg["handler"],
        "applicant": msg["applicant"],
        "matched_kind": msg["matched_kind"],
    }


def main():
    hours = int(os.environ.get("HOURS_BACK", "24"))
    limit = int(os.environ.get("LIMIT", "500"))

    db = SessionLocal()
    try:
        org = db.query(Organization).order_by(Organization.id).first()
        if not org:
            print("ERROR: No organization found in DB.")
            sys.exit(1)
        org_id = org.id

        print(f"Scanning Apple Mail (last {hours}h, limit {limit})...")
        messages = list_recent_messages(hours=hours, limit=limit)
        print(f"  Found {len(messages)} real-estate-related messages")

        added_em = 0
        added_leads = added_apps = added_sales = added_cmas = 0
        bp_count = 0

        for msg in messages:
            existing = db.query(EmailMessage).filter(
                EmailMessage.org_id == org_id,
                EmailMessage.external_id == msg["external_id"],
            ).first()
            if existing:
                continue

            prop = None
            if msg["property_address"]:
                prop = find_property(db, org_id, msg["property_address"], msg["unit"])

            em = EmailMessage(
                org_id=org_id,
                email_account_id=None,
                external_id=msg["external_id"],
                subject=msg["subject"],
                sender_email=msg["sender_email"],
                sender_name=msg["sender_name"],
                received_at=msg["received_at"],
                body_preview=msg["body_preview"],
                is_processed=True,
                matched_property_id=prop.id if prop else None,
                matched_kind=msg["matched_kind"],
            )
            db.add(em)
            db.flush()
            added_em += 1

            parsed = parsed_from_msg(msg)
            classified = classify_to_dict(msg)

            kind = msg["matched_kind"]
            if kind == "business_potential":
                bp_count += 1
            elif kind == "lead":
                _create_or_update_lead(db, org_id, prop, parsed, classified)
                added_leads += 1
            elif kind == "application":
                _create_or_update_application(db, org_id, prop, parsed, classified)
                added_apps += 1
            elif kind == "sales_deal":
                _create_or_update_sales_deal(db, org_id, parsed, classified)
                added_sales += 1
            elif kind == "cma":
                _create_or_update_cma(db, org_id, parsed, classified)
                added_cmas += 1

        db.commit()
        print(f"  New EmailMessage records: {added_em}")
        print(f"  Business potential:       {bp_count}")
        print(f"  Leads created:            {added_leads}")
        print(f"  Applications created:     {added_apps}")
        print(f"  Sales deals created:      {added_sales}")
        print(f"  CMAs created:             {added_cmas}")
        print("Done.")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
