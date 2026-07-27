# DealFlow — Architecture Plan

## Goal
Multi-tenant SaaS for property managers, deployed on Supabase + Vercel, ready for paid customers.

## Infrastructure

- **Supabase** — Postgres 17, Edge Functions (Deno), Storage, Auth
- **Vercel** — Frontend hosting (auto-deploy from `main`)
- **GitHub Pages** — NOD-ify (negotiatorsondemand.com) is static, calls Supabase Edge Functions

## Phased Roadmap

### Phase 1: Backend Scaffold ✅
- FastAPI reference app in `backend/` (ported to Supabase Edge Functions)
- Supabase Postgres schema (multi-tenant)
- Supabase Auth (email/password + JWT)
- Broker + streets-submit Edge Functions deployed

### Phase 2: Frontend + Billing
- Vercel frontend (dashboard SPA)
- Stripe billing integration (Free / Pro / Team tiers)
- Per-org data isolation (org_id on every row via RLS policies)

### Phase 3: Email Integrations
- Gmail API integration (OAuth, polling webhooks)
- Microsoft Graph API for Outlook
- IMAP fallback for other providers

### Phase 4: Storage Integrations
- Supabase Storage (replaces Google Drive / OneDrive)
- S3-compatible API for direct uploads

### Phase 5: Polish & Launch
- Marketing site (landing page on Vercel)
- Stripe self-serve signup
- Email support workflow
- Analytics (PostHog or Plausible)

## Tech Stack

### Backend (Supabase)
- **Supabase Postgres** — production DB
- **Supabase Edge Functions** (Deno) — API endpoints
- **Supabase Auth** — JWT auth, OAuth providers
- **Supabase Storage** — file uploads

### Frontend (Vercel)
- Static SPA or Vite app
- Supabase JS SDK for data access + auth
- No server-side rendering needed

### Legacy Reference (backend/)
- **FastAPI** — reference for porting logic to Edge Functions
- **SQLAlchemy 2.x** — reference for SQL queries
- **Jinja2 templates** — reference for frontend components

## Data Model (Core Tables)

```
organizations (id, name, plan, created_at)
users (id, org_id, email, password_hash, role, created_at)
email_accounts (id, org_id, provider, credentials_json, last_sync_at)
properties (id, org_id, address, unit, status, rent, bedrooms, ...)
leads (id, org_id, name, email, phone, property_id, source, status, received_at)
applications (id, org_id, applicant_name, property_id, unit, status, handler, received_at)
application_events (id, application_id, event_type, occurred_at, source_email_id)
sales_deals (id, org_id, property_id, status, list_price, received_at)
cma_requests (id, org_id, property_id, kind, status, requested_at)
property_files (id, org_id, property_id, kind, path, source, name)
broker_subscriptions (id, email, stripe_customer_id, status, created_at)
street_contest_entries (id, name, email, entry, created_at)
```

Every domain table has `org_id` for tenant isolation, enforced via Supabase RLS (Row Level Security) policies.

## Edge Functions

| Function | Path | Purpose |
|---|---|---|
| broker | /functions/v1/broker/* | $49/mo Stripe paywall for NOD-ify |
| streets-submit | /functions/v1/streets-submit | $100 Negotiator Challenge entries |
| (more to port) | | |

Deploy:
```bash
supabase functions deploy <name> --project-ref iubxycckgrplbpdbncfk
```

## Pricing Tiers

| Tier | Price | Leads/mo | Users | Email accounts |
|---|---|---|---|---|
| Free | $0 | 50 | 1 | 1 |
| Pro | $49/mo | Unlimited | 1 | 3 |
| Team | $149/mo | Unlimited | 10 | Unlimited |

## Local Dev Setup

```bash
# Supabase local (recommended)
brew install supabase/tap/supabase
supabase start
supabase functions serve

# Legacy FastAPI (reference only)
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Key Architectural Decisions

1. **Supabase Edge Functions over FastAPI** — serverless, no cold starts to manage, scales to zero
2. **Vercel for frontend** — global CDN, auto-deploy from git, free tier covers early users
3. **PostgreSQL with RLS** — tenant isolation at the database level, not app code
4. **Supabase Auth** — managed JWT auth, OAuth providers, no custom auth server
5. **Deno for Edge Functions** — TypeScript, fast cold starts, native Web APIs
