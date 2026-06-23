"""Sync engine: fetch from Graph API, parse emails, write to DB.

Called by:
- Manual "Sync now" button (POST /api/sync)
- Scheduled background job (APScheduler, every 5 min per org)
- Microsoft Graph webhook callback (Phase 2)
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    Organization, User, EmailAccount, EmailMessage,
    Property, Lead, LeadStatus,
    Application, ApplicationEvent, ApplicationStatus,
    SalesDeal, SalesStatus,
    CmaRequest,
)
from app.integrations.microsoft_graph import (
    fetch_user_profile, list_messages, parse_graph_message,
    refresh_access_token, token_expiry,
)
from app.integrations.email_parser import (
    classify_email, extract_property, detect_handler,
)


# ponytail: office bounce properties — not personal inventory, skip in property lists
BOUNCE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "bounce_properties.json")


def load_bounce_properties():
    """Load office properties available for bounce matching."""
    try:
        with open(BOUNCE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def match_bounce_properties(monthly_income: float, rent_threshold: float = 500):
    """Find office bounce properties within rent_threshold of lead's budget (income/3).
    
    Returns a formatted string for the bounce_to field, or None.
    """
    if not monthly_income or monthly_income <= 0:
        return None
    budget = monthly_income / 3  # standard qualifier: rent x 3
    matches = []
    for bp in load_bounce_properties():
        r = bp.get("rent")
        if r and abs(r - budget) <= rent_threshold:
            matches.append(f"{bp['address']} — ${r}/mo (+/${r - budget:.0f} from budget)")
    if not matches:
        return None
    return "Office bounce candidates: " + "; ".join(matches[:5])  # ponytail: max 5 suggestions


async def sync_account(account_id: int) -> dict:
    """Sync one email account: fetch messages, parse, insert/update DB."""
    db = SessionLocal()
    try:
        account = db.query(EmailAccount).filter(EmailAccount.id == account_id).first()
        if not account or not account.is_active:
            return {"status": "skipped", "reason": "inactive account"}
        # Refresh token if expired
        if account.token_expires_at and account.token_expires_at < datetime.now(timezone.utc):
            if not account.refresh_token:
                return {"status": "error", "reason": "no refresh token"}
            from app.config import get_settings
            s = get_settings()
            token = await refresh_access_token(s.ms_client_id, s.ms_client_secret, account.refresh_token)
            account.access_token = token["access_token"]
            if "refresh_token" in token:
                account.refresh_token = token["refresh_token"]
            account.token_expires_at = token_expiry(token["expires_in"])
        # Fetch messages
        msgs = await list_messages(
            account.access_token,
            top=50,
            delta_token=account.sync_cursor,
        )
        new_count = 0
        lead_count = 0
        app_count = 0
        sales_count = 0
        cma_count = 0
        for raw in msgs.get("value", []):
            parsed = parse_graph_message(raw)
            # Idempotency: skip if already stored
            existing = db.query(EmailMessage).filter(
                EmailMessage.external_id == parsed["external_id"]
            ).first()
            if existing:
                continue
            classified = classify_email(parsed["subject"], parsed["sender_email"])
            # Find matching property in org
            prop = None
            if classified["property_address"]:
                prop = find_property(db, account.org_id, classified["property_address"], classified["unit"])
            # Store raw email
            em = EmailMessage(
                org_id=account.org_id,
                email_account_id=account.id,
                external_id=parsed["external_id"],
                subject=parsed["subject"],
                sender_email=parsed["sender_email"],
                sender_name=parsed["sender_name"],
                received_at=datetime.fromisoformat(parsed["received_at"].replace("Z", "+00:00")) if parsed["received_at"] else None,
                body_preview=parsed["body_preview"],
                is_processed=True,
                matched_property_id=prop.id if prop else None,
                matched_kind=classified["matched_kind"],
            )
            db.add(em)
            db.flush()
            new_count += 1
            # Apply to domain tables based on kind
            if classified["matched_kind"] == "lead":
                _create_or_update_lead(db, account.org_id, prop, parsed, classified, classified.get("monthly_income"))
                lead_count += 1
            elif classified["matched_kind"] == "application":
                _create_or_update_application(db, account.org_id, prop, parsed, classified)
                app_count += 1
            elif classified["matched_kind"] == "sales_deal":
                _create_or_update_sales_deal(db, account.org_id, parsed, classified)
                sales_count += 1
            elif classified["matched_kind"] == "cma":
                _create_or_update_cma(db, account.org_id, parsed, classified)
                cma_count += 1
        # Save delta cursor for next sync
        if "@odata.deltaLink" in msgs:
            account.sync_cursor = msgs["@odata.deltaLink"]
        account.last_sync_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "status": "ok",
            "new_messages": new_count,
            "leads": lead_count,
            "applications": app_count,
            "sales": sales_count,
            "cmas": cma_count,
            "next_cursor": bool(account.sync_cursor),
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "reason": str(e)}
    finally:
        db.close()


def find_property(db: Session, org_id: int, addr: str, unit: Optional[str]) -> Optional[Property]:
    """Match by address (with light normalization) and unit."""
    from app.integrations.email_parser import normalize_addr
    norm = normalize_addr(addr + (f" {unit}" if unit else ""))
    for p in db.query(Property).filter(Property.org_id == org_id).all():
        pnorm = normalize_addr(p.address + (f" {p.unit}" if p.unit else ""))
        if pnorm == norm:
            return p
    # Fuzzy: address contains the input
    norm_no_unit = normalize_addr(addr)
    for p in db.query(Property).filter(Property.org_id == org_id).all():
        if normalize_addr(p.address) == norm_no_unit:
            return p
    return None


def _create_or_update_lead(db, org_id, prop, parsed, classified, monthly_income=None):
    """Insert a new lead (idempotent by email+subject)."""
    existing = db.query(Lead).filter(
        Lead.org_id == org_id,
        Lead.email == parsed["sender_email"],
        Lead.subject == parsed["subject"],
    ).first()
    if existing:
        return existing
    # ponytail: office bounce suggestions if we have income data
    bounce = match_bounce_properties(monthly_income) if monthly_income else None
    lead = Lead(
        org_id=org_id,
        property_id=prop.id if prop else None,
        name=classified.get("applicant") or parsed["sender_name"],
        email=parsed["sender_email"],
        phone=None,
        source="microsoft365",
        status=LeadStatus.NEW,
        subject=parsed["subject"],
        received_at=parsed["received_at"] or datetime.now(timezone.utc),
        raw_email_id=parsed["external_id"],
        monthly_income=monthly_income,
        bounce_to=bounce,
    )
    db.add(lead)


def _create_or_update_application(db, org_id, prop, parsed, classified):
    """Insert or update an application from email event."""
    applicant = classified.get("applicant") or parsed["sender_name"]
    if not applicant:
        return
    existing = db.query(Application).filter(
        Application.org_id == org_id,
        Application.applicant_name == applicant,
        Application.property_id == (prop.id if prop else None),
        Application.unit == classified.get("unit"),
    ).first()
    event_type = classified["event_type"]
    status_map = {
        "application_received": ApplicationStatus.APPLICATION_RECEIVED,
        "offer_sent": ApplicationStatus.OFFER_SENT,
        "approved": ApplicationStatus.APPROVED,
        "move_in": ApplicationStatus.MOVED_IN,
        "closed": ApplicationStatus.MOVED_IN,
    }
    new_status = status_map.get(event_type, ApplicationStatus.APPLICATION_RECEIVED)
    if existing:
        existing.status = new_status
        existing.last_update = datetime.now(timezone.utc)
        existing.handler = classified.get("handler") or existing.handler
        existing.event_count = (existing.event_count or 0) + 1
        app = existing
    else:
        app = Application(
            org_id=org_id,
            property_id=prop.id if prop else None,
            unit=classified.get("unit"),
            applicant_name=applicant,
            status=new_status,
            handler=classified.get("handler"),
            first_seen=datetime.now(timezone.utc),
            last_update=datetime.now(timezone.utc),
            days_in_pipeline=0,
            event_count=1,
        )
        db.add(app)
        db.flush()
    db.add(ApplicationEvent(
        application_id=app.id,
        event_type=event_type,
        occurred_at=datetime.now(timezone.utc),
        handler=classified.get("handler"),
        subject=parsed["subject"][:200],
    ))


def _create_or_update_sales_deal(db, org_id, parsed, classified):
    addr = classified.get("property_address") or "Unknown"
    existing = db.query(SalesDeal).filter(
        SalesDeal.org_id == org_id,
        SalesDeal.property_address == addr,
    ).first()
    status_map = {
        "agent_assigned": SalesStatus.LISTING_PREP,
        "new_listing": SalesStatus.ACTIVE_LISTING,
        "status_update": SalesStatus.ACTIVE_LISTING,
        "sale_cma": SalesStatus.CMA_REQUESTED,
        "closed": SalesStatus.CLOSED,
    }
    new_status = status_map.get(classified["event_type"], SalesStatus.ACTIVE_LISTING)
    if existing:
        existing.status = new_status
        existing.last_update = datetime.now(timezone.utc)
        existing.event_count = (existing.event_count or 0) + 1
    else:
        db.add(SalesDeal(
            org_id=org_id, property_address=addr, status=new_status,
            first_seen=datetime.now(timezone.utc), last_update=datetime.now(timezone.utc),
            event_count=1, days_idle=0,
        ))


def _create_or_update_cma(db, org_id, parsed, classified):
    addr = classified.get("property_address") or "Unknown"
    unit = classified.get("unit")
    existing = db.query(CmaRequest).filter(
        CmaRequest.org_id == org_id,
        CmaRequest.property_address == addr,
        CmaRequest.unit == unit,
    ).first()
    kind = "sale" if "sale_cma" in classified["event_type"] else "rental"
    now = datetime.now(timezone.utc)
    if existing:
        existing.request_count = (existing.request_count or 1) + 1
        existing.last_request = now
    else:
        db.add(CmaRequest(
            org_id=org_id, property_address=addr, unit=unit, kind=kind,
            status="pending", request_count=1,
            first_request=now, last_request=now,
        ))


async def sync_org(org_id: int) -> dict:
    """Sync all active email accounts for an org."""
    db = SessionLocal()
    try:
        accounts = db.query(EmailAccount).filter(
            EmailAccount.org_id == org_id,
            EmailAccount.is_active == True,
        ).all()
        results = []
        for acc in accounts:
            r = await sync_account(acc.id)
            results.append({"account_id": acc.id, "email": acc.email_address, **r})
        return {"status": "ok", "accounts": results}
    finally:
        db.close()
