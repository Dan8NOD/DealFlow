"""Email parser: classify and extract structured data from raw emails.

Reuses regex patterns from the local extract_*.py scripts.
Detects: new leads, applications, offers, sales events, CMA requests.
"""

import re
from typing import Optional, Dict, List, Tuple


def normalize_addr(s: str) -> str:
    if not s:
        return ""
    a = s.lower().strip()
    a = re.sub(r"[.,]", "", a)
    for old, new in [(" street", " st"), (" avenue", " ave"), (" road", " rd"),
                      (" drive", " dr"), (" boulevard", " blvd"), (" place", " pl"),
                      (" terrace", " ter"), (" court", " ct")]:
        a = a.replace(old, new)
    a = " ".join(a.split())
    for city in [" chicago", " calumet city", " riverdale", " dolton", " joliet",
                 " cicero", " naperville", " woodstock", " downers grove",
                 " east", " homewood", " woodridge"]:
        a = a.replace(city, "")
    a = a.replace(", il", "").replace(" il", "").strip()
    return a


# Key senders (Westward360 application handlers)
W360_HANDLERS = {
    "marians@westward360.com": "Marian Sabucor",
    "mirasola@westward360.com": "Mirasol Atablanco",
    "franchescap@westward360.com": "Franchesca Paradero",
    "sarab@westward360.com": "Sara Baker",
    "stephenf@westward360.com": "Stephen Fisher",
    "applications@westward360.com": "Applications Team",
}

# Vendor senders (external lead sources)
LEAD_SOURCES = {
    "outbound@email.showmojo.com": "ShowMojo",
    "consumer@e.mail.realtor.com": "Realtor.com",
    "dse@docusign.net": "DocuSign",
}


def extract_property(subject: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract (property_address, unit) from a subject line."""
    s = subject
    # 14301 S Edbrooke Ave, Riverdale, IL 60827 (sales - exact match list)
    for known in ["14301 S Edbrooke Ave, Riverdale, IL 60827",
                  "603 Greenbay Ave, Calumet City, IL",
                  "754 W California Ter #2",
                  "1017 W Dakin #1", "12701 S Green St",
                  "5250 S Nagle Ave, Chicago, IL 60638",
                  "201 E 143rd St, Dolton, IL"]:
        if known.split(",")[0].lower() in s.lower():
            return known, None
    # "[Westward360] Application for 6702 S Wood St UNIT 1B - Stephens"
    m = re.search(r'(?:Application for|Offer for|Offer:?|Rental CMA Needed|New W360 Listing:?|SALE -)\s*[-–]?\s*(.+?)(?:\s+(?:UNIT|Unit|unit|Apt|Apartment|#)\s*([\w\-]+))?(?:\s*[-–]\s*(.+))?$', s)
    if m:
        addr = m.group(1).strip().rstrip(".,")
        unit = m.group(2).strip() if m.group(2) else None
        return addr, unit
    # "Ursula Taylor is interested in 14132 S Highlawn Ave."
    m = re.search(r'(?:interested in|requesting information about|inquiry for)\s+(.+?)(?:\.|$)', s)
    if m:
        return m.group(1).strip().rstrip(".,"), None
    return None, None


def detect_event_type(subject: str) -> str:
    """Classify subject into event type."""
    s = subject.lower()
    if "thank you for your application" in s or "application for" in s:
        return "application_received"
    if "offer for" in s or s.startswith("offer "):
        return "offer_sent"
    if "approved" in s or "lease sign" in s or "signed" in s and "docusign" in s:
        return "approved"
    if "welcome" in s and "important" in s:
        return "move_in"
    if "closing confirmation" in s:
        return "closed"
    if "sales status thread" in s or "sales status thread" in s:
        return "status_update"
    if "sales agent for" in s:
        return "agent_assigned"
    if "showing confirmed" in s or "showing feedback" in s:
        return "showing"
    if "rental cma needed" in s:
        return "cma_needed"
    if "sale -" in s and "cma" in s:
        return "sale_cma"
    if "new w360 listing" in s:
        return "new_listing"
    if "docusign" in s or "dse" in s:
        return "docusign"
    if "is interested in" in s or "is requesting information" in s or "new lead at" in s:
        return "new_lead"
    return "other"


def detect_handler(sender_email: str) -> Optional[str]:
    """Look up handler name from sender email."""
    return W360_HANDLERS.get(sender_email.lower().strip())


def extract_applicant(subject: str) -> Optional[str]:
    """Try to extract applicant name from subject patterns."""
    # "Application for 6702 S Wood St UNIT 1B - Stephens"
    m = re.search(r'[-–]\s*([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+)?)\s*(?:_\d+)?$', subject)
    if m:
        return m.group(1).strip()
    # "Ursula Taylor is interested in ..."
    m = re.search(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+is (?:interested|requesting)', subject)
    if m:
        return m.group(1).strip()
    # "Yvonne Barnes" (from "New realtor.com lead - Yvonne Barnes")
    m = re.search(r'(?:New realtor\.com lead|lead)\s*[-–]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)', subject)
    if m:
        return m.group(1).strip()
    return None


def classify_email(subject: str, sender_email: str) -> Dict:
    """Classify an email and extract structured fields."""
    event_type = detect_event_type(subject)
    addr, unit = extract_property(subject)
    handler = detect_handler(sender_email)
    applicant = extract_applicant(subject)
    is_lead_source = sender_email.lower() in LEAD_SOURCES
    is_w360 = "westward360.com" in sender_email.lower()
    return {
        "event_type": event_type,
        "property_address": addr,
        "unit": unit,
        "handler": handler,
        "applicant": applicant,
        "is_lead_source": is_lead_source,
        "is_w360": is_w360,
        "matched_kind": _kind_from_event(event_type),
    }


def _kind_from_event(event_type: str) -> str:
    if event_type in ("application_received", "offer_sent", "approved", "showing"):
        return "application"
    if event_type in ("new_lead",):
        return "lead"
    if event_type in ("status_update", "agent_assigned", "new_listing", "closed", "sale_cma"):
        return "sales_deal"
    if event_type in ("cma_needed",):
        return "cma"
    return "other"
