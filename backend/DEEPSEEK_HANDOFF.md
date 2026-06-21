I'm handing off my Renter Portal project to you for a major refinement push. The portal is a FastAPI + SQLite app at /Users/danielcruz/Desktop/Leads/saas/backend/. I use this on a large tablet (iPad Pro size) while showing apartments, and I constantly switch between Obsidian notes, spreadsheets from ShowMojo, my 6 email accounts in Apple Mail, and Google searches about properties. The goal: everything unified into one tablet-first portal so I don't context-switch.

────────────────────────────────────────────
CURRENT STATE
────────────────────────────────────────────

Database: renter_portal.db at /Users/danielcruz/Desktop/Leads/saas/backend/
Tables: properties (251 rows, 28 columns), leads (884 rows, 23 columns), applications (324 rows), sales_deals (7), cma_requests (27), comments (0), email_messages (0), email_accounts (0), property_files (360), application_events (527)

KEY MODELS:

Property — 28 columns:
  id, org_id, address, unit, city, state, zip_code, bedrooms, bathrooms, square_feet, rent, status (AVAILABLE/RENTED/OCCUPIED/OFF_MARKET/FOR_SALE), tenant_name, available_date, notes, 
  # Obsidian-enriched fields (12):
  pet_restrictions, utilities_included, utilities_paid_by_tenant, parking, storage, laundry, asset_manager, lockbox_code, listing_description, mls_id, cma_link, showing_instructions,
  created_at

Lead — 23 columns:
  id, org_id, property_id, name, email, phone, source, status (NEW/CONTACTED/QUALIFIED/CLOSED/LOST), subject, received_at, days_old, raw_email_id, monthly_income, income_source, interested_in_buying, upsell_eligible, notes,
  # Spreadsheet-enriched fields (5):
  move_in_date, last_called, call_outcome, call_notes, bounce_to,
  created_at

Application — 18 columns:
  id, org_id, property_id, unit, applicant_name, status (APPLICATION_RECEIVED/OFFER_SENT/WELCOME_SENT/APPROVED/LEASE_SIGNED/MOVED_IN/DENIED), handler, first_seen, last_update, days_in_pipeline, event_count, needs_review, monthly_income, credit_score, move_in_date, pets, notes, created_at

ApplicationEvent — 7 columns: id, application_id, event_type, occurred_at, handler, source_email_id, subject

SalesDeal — 11 columns: id, org_id, property_address, status, list_price, transaction_coordinator, first_seen, last_update, days_idle, event_count, created_at

CmaRequest — 9 columns: id, org_id, property_address, unit, kind, status, request_count, first_request, last_request, listed_at

Comment — 7 columns: id, org_id, user_id, record_type, record_id, content, created_at

PropertyFile — 10 columns: id, org_id, property_id, kind, name, path, source, size_bytes, obsidian_vault, section, created_at

EmailMessage — 13 columns: id, org_id, email_account_id, external_id, subject, sender_email, sender_name, received_at, body_preview, is_processed, matched_property_id, matched_kind, created_at

EmailAccount — 14 columns: id, org_id, user_id, provider, email_address, access_token, refresh_token, token_expires_at, webhook_id, webhook_expires_at, last_sync_at, sync_cursor, is_active, created_at

One user (danielcruz@westward360.com) in one organization (id=1). For production auth, there's a single hardcoded dev user. You'll need to handle login flow.

ENRICHMENT SOURCES:
1. Obsidian vault at /Users/danielcruz/Documents/Real Estate Deals/Real Estate/LEASING/ — 39 markdown notes per property with structured data (pet rules, utilities, lockbox codes, MLS IDs, CMA links, listing descriptions, tenant info, activity reports). Parsed by scripts/sync_obsidian.py.
2. Spreadsheet at /Users/danielcruz/Desktop/Leads/renter_leads_calling_v5_20260619.xlsx — 741 leads with property master, call tracking, move-in dates, bounce-to suggestions. Parsed by scripts/sync_spreadsheet.py.
3. Run both: cd backend && python3 scripts/run_sync.py

SYNC SCRIPTS LOCATIONS:
- /Users/danielcruz/Desktop/Leads/saas/backend/scripts/sync_obsidian.py
- /Users/danielcruz/Desktop/Leads/saas/backend/scripts/sync_spreadsheet.py
- /Users/danielcruz/Desktop/Leads/saas/backend/scripts/run_sync.py

TEMPLATES:
- /Users/danielcruz/Desktop/Leads/saas/backend/app/templates/base.html — minimal base wrapper
- /Users/danielcruz/Desktop/Leads/saas/backend/app/templates/dashboard.html — 759-line single-page app (Jinja2 rendering) with stats, tables for leads/apps/sales/CMAs, inline editing via PATCH
- /Users/danielcruz/Desktop/Leads/saas/backend/app/templates/tenant.html — simple public tenant view for one property
- /Users/danielcruz/Desktop/Leads/saas/backend/app/templates/showing.html — my first attempt at a mobile showing page (works but is basic)
- /Users/danielcruz/Desktop/Leads/saas/backend/app/templates/landing.html, login.html, signup.html

API ROUTES (in /Users/danielcruz/Desktop/Leads/saas/backend/app/routers/dashboard.py):
- GET /api/properties — list with sort, filter by status, enriched flag
- GET /api/properties/showing-sheet — compact showing endpoint, sorted by status priority, filters for lockbox/bedrooms/rent, returns lead count + active app count per property
- GET /api/leads — list with status filter
- GET /api/applications — list with status filter
- GET /api/sales, /api/cmas — list endpoints
- PATCH /api/properties/{id}, /api/leads/{id}, /api/applications/{id}, /api/sales/{id}, /api/cmas/{id} — inline editing
- POST /api/comments, GET /api/comments/{type}/{id}
- GET /showing — mobile showing page (my basic version)
- GET /dashboard — main portal page

STARTUP: /Users/danielcruz/Desktop/Leads/saas/backend/app/main.py — FastAPI app, creates tables on startup, runs _ensure_columns for migrations, includes auth + dashboard + microsoft routers. Server: cd backend && source .venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000

────────────────────────────────────────────
WHAT I NEED YOU TO BUILD
────────────────────────────────────────────

1. TABLET-FIRST RESPONSIVE UI. The current dashboard.html is desktop-only and doesn't work on my large tablet (iPad Pro). Redesign the frontend as a SPA that renders beautifully on a 12.9" tablet in landscape AND portrait. This means:
   - Touch-friendly tap targets (min 44px)
   - Sidebar or bottom nav for tablet thumb-reach
   - Split-pane view on landscape: property list on left, detail on right
   - Swipe gestures for navigating between sections
   - Dark mode option (I view this outside in sunlight often)

2. PROPERTY DETAIL HUB. When I tap a property, show a full detail page that consolidates:
   - ALL the Obsidian data (pet rules, utilities, parking, lockbox codes, showing instructions, listing description, CMA link)
   - Lead activity for that property (count, recent leads, their move-in dates, call outcomes)
   - Application pipeline for that property (who applied, status, handler, days in pipeline)
   - Sales data if it's a sales listing
   - An embedded "quick sheet" section with only the info I need while standing at the door: lockbox code, unit features, rent, current tenant status
   - A "bounce-to" section showing alternative properties for when this one doesn't work out

3. SEARCH THAT REPLACES GOOGLE. I search properties all the time. Build search into the portal:
   - Full-text search across property addresses, MLS IDs, tenant names, notes
   - Search leads by name, email, phone
   - Search applications by applicant name, handler
   - Results should surface the right property card immediately

4. EMAIL INTEGRATION FRAMEWORK. The email_accounts and email_message tables exist but are empty. I have 6 email accounts in Apple Mail. Instead of building full OAuth now, build:
   - A "Mail" tab in the portal where I can paste or forward emails and they get attached to the right property/lead
   - ShowMojo emails should auto-link to properties and leads
   - An email log per property showing recent inquiries
   - The sync_engine and email_parser exist at /Users/danielcruz/Desktop/Leads/saas/backend/app/integrations/ — wire them up

5. SHOWING SHEET 2.0. My current showing.html works but needs:
   - Loading spinner for when I'm on a slow connection at a showing
   - Offline-capable (ServiceWorker cache of property data)
   - One-tap access to lockbox code (tapping it copies to clipboard with a toast notification)
   - A "Start Showing" mode that walks through: here's the lockbox → unit features → common questions → nearby amenities
   - Integration with the bounce-to leads so if they don't like this unit, I can immediately show them alternatives from my portfolio

6. PROPERTY FILES / PHOTOS. The property_files table has 360 records scanned from disk. The portal should surface:
   - A media gallery per property (photos, videos)
   - Links to Google Drive folders stored in property_files
   - During a showing, being able to pull up photos of the unit

7. DATA QUALITY. Many properties have duplicates (same address different formatting):
   - "1141 S Francisco Ave #1F" vs "1141 s francisco #1F" vs "1141 Francisco #2F"
   - Build a deduplication tool in the portal that merges duplicate properties, preserving all leads/applications/files

────────────────────────────────────────────
FILES YOU'LL NEED TO EDIT/CREATE
────────────────────────────────────────────
/Users/danielcruz/Desktop/Leads/saas/backend/app/templates/dashboard.html — rewrite as tablet SPA
/Users/danielcruz/Desktop/Leads/saas/backend/app/templates/showing.html — upgrade to Showing Sheet 2.0
/Users/danielcruz/Desktop/Leads/saas/backend/app/routers/dashboard.py — add new API endpoints as needed
/Users/danielcruz/Desktop/Leads/saas/backend/app/models.py — add anything new
/Users/danielcruz/Desktop/Leads/saas/backend/app/main.py — register new routes

FRONTEND APPROACH: Use vanilla JS or a lightweight framework (Alpine.js, htmx, or just vanilla). The template files use Jinja2 server-side rendering mixed with client-side JS. Keep it simple — no build step, no npm. The server already uses Jinja2Templates. You can serve plain HTML from template files and hit the JSON API from JS. Use CSS Grid + Flexbox for responsive layout, no CSS framework needed (or use a CDN-loaded one like Bulma or Pico CSS if it helps).

START: Read the key files first (models.py, dashboard.py, main.py, dashboard.html, showing.html) to understand the full shape, then build. Run the server to test: cd /Users/danielcruz/Desktop/Leads/saas/backend && source .venv/bin/activate && python3 -c "from app.main import app; print('App loads OK')"