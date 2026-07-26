# DealFlow — SaaS

Multi-tenant SaaS for property managers and real estate agents. Tracks rental leads, applications, sales deals, CMA requests, and property files in one dashboard.

## Status

✅ **Phase 1 (Backend Scaffold)** — done (FastAPI reference in `backend/`)
✅ **Supabase migration** — Postgres + Edge Functions + Storage
⏳ **Vercel frontend** — in progress
⏳ **Phase 2 (Billing + Auth polish)** — TODO
⏳ **Phase 3 (Email integrations)** — TODO

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full plan.

## Infrastructure

- **Supabase** — Postgres DB, Edge Functions (Deno), Storage, Auth
  - Project: iubxycckgrplbpdbncfk
  - Dashboard: https://supabase.com/dashboard/project/iubxycckgrplbpdbncfk
  - Edge Functions: https://iubxycckgrplbpdbncfk.supabase.co/functions/v1/
- **Vercel** — Frontend hosting (auto-deploys from `main`)
- **GitHub Pages** — NOD-ify (negotiatorsondemand.com) calls the broker Edge Function

## Local Development

```bash
git clone https://github.com/Dan8NOD/DealFlow.git
cd DealFlow

# Option A: Supabase local dev (recommended)
brew install supabase/tap/supabase
supabase start  # local Postgres + Auth + Functions
supabase functions serve  # local edge functions at localhost:54321

# Option B: Legacy FastAPI (reference only)
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://postgres:***@db.iubxycckgrplbpdbncfk.supabase.co:5432/postgres?sslmode=require
uvicorn app.main:app --reload
```

## Project Structure

```
DealFlow/
├── supabase/
│   ├── config.toml          # Supabase project config
│   └── functions/           # Deno Edge Functions
│       ├── broker/          # $49/mo Stripe paywall (NOD-ify calls this)
│       └── streets-submit/  # $100 Negotiator Challenge
├── backend/                 # Legacy FastAPI (reference for porting)
│   ├── app/
│   │   ├── main.py          # FastAPI entry (reference)
│   │   ├── routers/         # Port these to Edge Functions
│   │   └── templates/       # Port to Vercel frontend
│   └── requirements.txt
├── deploy/
│   └── QUICKSTART.md        # Supabase + Vercel deploy guide
├── docker-compose.yml       # Local dev (legacy)
└── OPS.md                   # Read this first
```

## Deploy

See [deploy/QUICKSTART.md](deploy/QUICKSTART.md) for the full Supabase + Vercel setup.

### Edge Functions
```bash
supabase functions deploy broker --project-ref iubxycckgrplbpdbncfk
supabase functions deploy streets-submit --project-ref iubxycckgrplbpdbncfk
```

### Frontend
Push to `main` → Vercel auto-deploys.

### Secrets
```bash
supabase secrets set STRIPE_SECRET_KEY=... STRIPE_PRICE_ID=... --project-ref iubxycckgrplbpdbncfk
```

## Data Model

Multi-tenant by `org_id`. Every domain table has `org_id` foreign key to `organizations.id`.

| Table | Purpose |
|---|---|
| organizations | Tenants (one per real estate company) |
| users | Login accounts, role (owner/admin/member) |
| properties | Rental/sale listings with status |
| leads | New inquiries from Zillow/Trulia/etc |
| applications | Application pipeline with events |
| sales_deals | Active/closed sales |
| cma_requests | CMA requests needing comp report |
| property_files | Linked documents |

## Pricing Tiers

| Tier | Price | Limits |
|---|---|---|
| Free | $0 | 50 leads/mo, 1 user |
| Pro | $49/mo | Unlimited leads, 3 email accounts |
| Team | $149/mo | Unlimited users, unlimited emails |

## API Endpoints (Edge Functions)

```
POST /functions/v1/broker/verify     Verify broker subscription token
POST /functions/v1/streets-submit    Submit $100 Negotiator Challenge entry
GET  /health                          Supabase health check
```
