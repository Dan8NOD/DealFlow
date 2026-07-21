# Renter Portal — Ops Handoff (read this first, nothing else)

You are minimax-m3 (or any cheap model) maintaining this app. This file is
the entire briefing. Do NOT explore before reading it. Do NOT read
AGENTS.md/CLAUDE.md/README.md/DEPLOY_NOW.md — stale. This file is current.

## What this is

FatCatAM / NOD Academy portal ("DealFlow" repo). FastAPI + Jinja2 + SQLAlchemy,
server-rendered. Owner: Dan Cruz (dancruzhomes@gmail.com).
Live: https://renter-portal-1-jajv.onrender.com

- Repo: github.com/Dan8NOD/DealFlow (local: ~/Desktop/Active_Leads/saas)
- WARNING: ~/Projects/renter-portal is a STALE diverged copy. Never edit it.
- Login: dancruzhomes@gmail.com / Leads2025!
- Login POSTs form data (NOT JSON): fields `email`, `password` to /auth/login.
  Success = 303 redirect.
- Deploy: `git push origin main` → Render auto-deploys ~60-90s. Verify after.

## Layout (only these matter)

```
backend/app/main.py        # app entry, CORS (allow_origins=["*"]), router registration, startup create_all
backend/app/models.py      # all DB models — add columns/tables here
backend/app/config.py      # Settings from env vars
backend/app/auth.py        # JWT; require_user (HTML, 307 redirect) vs get_current_user (API, 401)
backend/app/routers/       # auth dashboard nod trainer calendly fatcat streets broker
backend/app/templates/     # Jinja2 HTML; dashboard.html is the SPA (inline JS, no framework)
render.yaml                # startCommand: cd backend && uvicorn app.main:app
scripts/verify.py          # run after EVERY deploy: python3 scripts/verify.py
```

## Hard rules (violating these breaks prod)

1. Local dev DB = SQLite, prod = Postgres. NEVER use strftime/date()/
   GROUP_CONCAT/ifnull in raw SQL. Use SQLAlchemy funcs or branch on
   `db.get_bind().dialect.name`. #1 cause of opaque 500s on Render.
2. Auth: HTML routes use `require_user` (307 → /login). API routes use
   `get_current_user` (401 JSON). Never swap.
3. Never add a second `@router.get("/same-path")` — replace the handler body
   in place. Duplicate registrations 422 every request.
4. Pydantic `le=` caps: dashboard JS fetches `?limit=500`. Any endpoint with
   `le=<500` → 422 → dashboard silently shows zeros.
5. Static paths before parameterized paths for the same HTTP method.
6. Never `git add -A` when .env changed — .env must never be committed.
   Use `git add <files>`. If .env is ever committed, rotate ALL keys in it.
7. After push, wait 90s before verifying. Cloudflare caches HTML ~10min —
   verify with curl (hits origin), or append ?cb=<ts>.
8. New tables auto-create via Base.metadata.create_all on startup — no
   migrations for additive changes.

## Env vars (Render dashboard, never in repo)

STRIPE_SECRET_KEY, STRIPE_PRICE_ID, STRIPE_WEBHOOK_SECRET, CALENDLY_API_KEY,
DATABASE_URL (auto).

## Key features map

- /dashboard — real estate SPA (leads kanban, properties, gadgets)
- /nod — NOD Academy (students, sessions, coaching)
- /products — product ladder + Stripe proxy (/api/stripe/*, key server-side)
- /nodify — MixMatch asset dashboard (the GAME lives on GH Pages — never copy it here)
- /calendly — upcoming coaching sessions, Calendly API v2, poll on load
- /streets — $100 Negotiator Challenge admin (StreetContestEntry model)
- /api/broker/* — $49/mo Stripe subscription paywall for NOD-ify. Access token
  IS the auth (no login). MixMatch.html on GH Pages calls /api/broker/verify.
  BrokerSubscription model is defined INSIDE broker.py — self-contained.
- /contact, /ad, /sell, /buy — public lead capture → POST /api/leads-from-landing

## How to make a change

1. Read the ONE file you're editing. Nothing else.
2. Shortest working diff. No new abstractions, deps, or "for later".
3. Sanity: `cd backend && python3 -c "from app.main import app"` → "imports ok".
4. `git add <files> && git commit -m "..." && git push origin main`
5. Sleep 90, then `python3 scripts/verify.py`. 8/8 = done. Less: fix first.
6. Report: what changed, verify result, live URL. Three lines max.

## If prod is broken

- 404 on working routes → crashed; `git commit --allow-empty -m "redeploy" && git push`
- 500 on one endpoint → check for SQLite-only SQL (rule 1).
- Dashboard zeros but 200 → 422 from le= cap (rule 4); check /api/debug-dashboard.
- Push landed but live unchanged → Render webhook stale; manual deploy on
  dashboard.render.com, or empty-commit trick.

## Verify

`python3 scripts/verify.py` — login, /health, /dashboard, /contact, /api/leads,
/api/dashboard.json, creates+finds a test lead (source=Verify). 8/8 expected.
Creates one test lead; delete via dashboard if undesired.
