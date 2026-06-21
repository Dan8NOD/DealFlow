"""Apple Mail extraction from the local macOS Mail Envelope Index.

Read-only SQLite queries against ~/Library/Mail/V10/MailData/Envelope Index.
Classifies messages using the same email_parser used by the Graph sync engine.
"""

import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

from app.integrations.email_parser import classify_email

MAIL_DB = os.path.expanduser("~/Library/Mail/V10/MailData/Envelope Index")

# Keywords that suggest a message is a real-estate business opportunity
# even when it doesn't match the standard lead/application/sales patterns.
BUSINESS_POTENTIAL_KEYWORDS = [
    "rent out", "renting out", "for rent", "new property", "new listing",
    "investment property", "investment", "group rental", "group",
    "looking to rent", "want to rent", "need to rent", "property management",
    "rent my", "renting my", "rental property", "lease out", "lease my",
    "leasing out", "new rental", "available for rent", "house for rent",
    "apartment for rent", "condo for rent", "townhome for rent",
    "real estate opportunity", "potential listing", "listing opportunity",
]


def _is_business_potential(subject: str, body: str = "") -> bool:
    text = f"{subject} {body}".lower()
    return any(kw in text for kw in BUSINESS_POTENTIAL_KEYWORDS)


def _received_ts(ts: Optional[int]) -> Optional[datetime]:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def list_recent_messages(hours: int = 24, limit: int = 500) -> List[Dict]:
    """Return recent Apple Mail messages classified by the email parser.

    Each dict contains:
      external_id, subject, sender_email, sender_name, received_at,
      body_preview, event_type, property_address, unit, handler,
      applicant, matched_kind, is_business_potential
    """
    if not os.path.exists(MAIL_DB):
        return []

    since = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())

    conn = sqlite3.connect(f"file:{MAIL_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sql = """
        SELECT
            m.global_message_id AS external_id,
            s.subject AS subject,
            a.address AS sender_email,
            a.comment AS sender_name,
            m.date_received AS date_received
        FROM messages m
        JOIN addresses a ON m.sender = a.ROWID
        JOIN subjects s ON m.subject = s.ROWID
        WHERE m.deleted = 0
          AND m.date_received > ?
        ORDER BY m.date_received DESC
        LIMIT ?
    """
    cur.execute(sql, (since, limit))
    rows = cur.fetchall()
    conn.close()

    results = []
    for row in rows:
        subject = row["subject"] or ""
        sender_email = row["sender_email"] or ""
        sender_name = row["sender_name"] or ""
        received_at = _received_ts(row["date_received"])
        classified = classify_email(subject, sender_email)
        body_preview = ""  # Could be expanded to parse .emlx later

        matched_kind = classified.get("matched_kind") or "other"
        is_bp = False
        if matched_kind == "other" and _is_business_potential(subject, body_preview):
            matched_kind = "business_potential"
            is_bp = True

        # Skip purely unrelated mail
        if matched_kind == "other":
            continue

        results.append({
            "external_id": str(row["external_id"]),
            "subject": subject,
            "sender_email": sender_email,
            "sender_name": sender_name,
            "received_at": received_at,
            "body_preview": body_preview,
            "event_type": classified.get("event_type"),
            "property_address": classified.get("property_address"),
            "unit": classified.get("unit"),
            "handler": classified.get("handler"),
            "applicant": classified.get("applicant"),
            "matched_kind": matched_kind,
            "is_business_potential": is_bp,
        })

    return results
