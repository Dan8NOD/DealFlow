#!/usr/bin/env python3
"""Sync ShowMojo iCal feed → Renter Portal API + Google Calendar.

Pulls the ShowMojo calendar.ics feed, parses showings, and:
1. Posts new leads to the Renter Portal API (dedup by email/phone)
2. Creates Google Calendar events for each showing

Usage:
    python3 showmojo_sync.py [--dry-run]

Cron: every 30 minutes
"""
import subprocess, sys, os, re, json, urllib.request, urllib.parse
from datetime import datetime, timezone

ICAL_URL = "https://showmojo.com/accounts/91c8965bd30a99d3de66e5a1f2cf4721/calendar.ics"
PORTAL_URL = "https://renter-portal-1-jajv.onrender.com"
PORTAL_EMAIL = "dancruzhomes@gmail.com"
PORTAL_PASSWORD = "Leads2025!"

def fetch_ical():
    req = urllib.request.Request(ICAL_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")

def parse_ical(text):
    """Parse VEVENTs into structured leads."""
    events = text.split("BEGIN:VEVENT")[1:]
    leads = []
    for e in events:
        # Parse DTSTART
        dt_m = re.search(r"DTSTART:(\d{8}T\d{6}Z)", e)
        showing_time = None
        if dt_m:
            try:
                showing_time = datetime.strptime(dt_m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            except:
                pass

        # Parse DESCRIPTION for lead details
        desc_m = re.search(r"DESCRIPTION:(.*?)(?:\r?\nSUMMARY:|\r?\nEND:)", e, re.DOTALL)
        desc = desc_m.group(1) if desc_m else ""
        desc = desc.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").strip()

        name_m = re.search(r"Name:\s*(.+)", desc)
        phone_m = re.search(r"Phone:\s*(.+)", desc)
        email_m = re.search(r"Email:\s*(.+)", desc)

        # Parse SUMMARY for property address
        sum_m = re.search(r"SUMMARY:Showing at (.+?)(?:\s*\(|\r?\n)", e)
        address = sum_m.group(1).strip() if sum_m else ""

        # Parse screening answers
        move_in_m = re.search(r"When do you need to move.*?\n\s*(.+)", desc)
        credit_m = re.search(r"financial reliability.*?\n\s*(.+)", desc)
        tenants_m = re.search(r"How many tenants.*?\n\s*(\d+)", desc)

        confirmed = "Confirmed" in desc and "Not Yet Confirmed" not in desc

        name = name_m.group(1).strip() if name_m else ""
        phone = (phone_m.group(1).strip() if phone_m else "").replace(".", "-")
        email = (email_m.group(1).strip() if email_m else "").replace("\\n", "").strip()

        if not name and not phone:
            continue

        leads.append({
            "name": name,
            "phone": phone,
            "email": email,
            "property_address": address,
            "source": "ShowMojo",
            "status": "NEW",
            "showing_time": showing_time.isoformat() if showing_time else None,
            "confirmed": confirmed,
            "move_in_date": move_in_m.group(1).strip() if move_in_m else None,
            "credit_note": credit_m.group(1).strip() if credit_m else None,
            "tenant_count": tenants_m.group(1).strip() if tenants_m else None,
        })
    return leads

def portal_login():
    """Login to Renter Portal, get session cookie."""
    data = urllib.parse.urlencode({"email": PORTAL_EMAIL, "password": PORTAL_PASSWORD}).encode()
    req = urllib.request.Request(f"{PORTAL_URL}/auth/login", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    # Don't follow redirects — we just want the cookie
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), NoRedirectHandler())
    try:
        opener.open(req, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code != 303:
            raise
    cookies = {c.name: c.value for c in cj}
    return cookies.get("session_token", "")

def portal_create_lead(token, lead):
    """POST a lead to the portal API."""
    payload = {
        "name": lead["name"],
        "phone": lead["phone"],
        "email": lead["email"],
        "property_address": lead["property_address"],
        "source": "ShowMojo",
        "status": "NEW",
    }
    if lead.get("move_in_date"):
        payload["monthly_income"] = None
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"{PORTAL_URL}/api/leads", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Cookie", f"session_token={token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200 or r.status == 201
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return False  # duplicate
        return False
    except:
        return False

def portal_get_existing_emails(token):
    """Fetch existing lead emails/phones for dedup — all statuses."""
    # ponytail: fetch all statuses so COLD/LOST leads don't get re-inserted
    all_emails, all_phones = set(), set()
    for status in ["NEW", "CONTACTED", "QUALIFIED", "COLD", "LOST"]:
        req = urllib.request.Request(
            f"{PORTAL_URL}/api/leads?limit=2000&status={status}",
            headers={"Cookie": f"session_token={token}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                leads = json.loads(r.read())
                all_emails |= {l.get("email","").lower() for l in leads if l.get("email")}
                all_phones |= {re.sub(r"\D","",l.get("phone","")) for l in leads if l.get("phone")}
        except:
            pass
    return all_emails, all_phones

class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

# ponytail: No Google Calendar API needed — ShowMojo iCal feed is subscribed
# directly in Apple Calendar + Google Calendar. No token dependency, no auth.
# To add: Settings → Calendar → Accounts → Add → Other → Subscribe to URL:
#   https://showmojo.com/accounts/91c8965bd30a99d3de66e5a1f2cf4721/calendar.ics

def main():
    dry_run = "--dry-run" in sys.argv
    print(f"ShowMojo Sync — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Mode: {'DRY-RUN' if dry_run else 'LIVE'}")

    # 1. Fetch iCal
    print("\n1. Fetching ShowMojo iCal feed...")
    ical_text = fetch_ical()
    leads = parse_ical(ical_text)
    print(f"   Parsed {len(leads)} showings")

    # 2. Login to portal
    print("\n2. Logging into Renter Portal...")
    token = portal_login()
    if not token:
        print("   FAILED — could not get session token")
        return
    print("   OK")

    # 3. Dedup
    print("\n3. Checking for duplicates...")
    existing_emails, existing_phones = portal_get_existing_emails(token)
    new_leads = []
    for lead in leads:
        email = lead["email"].lower()
        phone_digits = re.sub(r"\D", "", lead["phone"])
        if email and email in existing_emails:
            continue
        if phone_digits and phone_digits in existing_phones:
            continue
        new_leads.append(lead)
    print(f"   {len(new_leads)} new leads (deduped from {len(leads)})")

    # 4. Import new leads
    if not dry_run and new_leads:
        print(f"\n4. Importing {len(new_leads)} leads to portal...")
        imported = 0
        for lead in new_leads:
            ok = portal_create_lead(token, lead)
            if ok:
                imported += 1
                print(f"   ✓ {lead['name']} — {lead['property_address']}")
            else:
                print(f"   ⊘ Skipped (dup?): {lead['name']}")
        print(f"   Imported: {imported}")
    else:
        print(f"\n4. {'No new leads to import' if not new_leads else '[DRY-RUN] skipped import'}")

    # 5. Calendar — no API needed, iCal feed is subscribed directly
    upcoming = [l for l in leads if l.get("showing_time") and datetime.fromisoformat(l["showing_time"]) > datetime.now(timezone.utc)]
    print(f"\n5. Calendar: {len(upcoming)} upcoming showings (subscribed via iCal — no API needed)")

    print(f"\n✓ Sync complete — {datetime.now().strftime('%H:%M:%S')}")

if __name__ == "__main__":
    main()
