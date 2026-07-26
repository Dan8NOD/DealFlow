# DealFlow — Ops Handoff (read this first, nothing else)

You are minimax-m3 (or any cheap model) maintaining this app. This file is
the entire briefing. Do NOT explore before reading it. Do NOT read
AGENTS.md/CLAUDE.md/README.md unless this file points you there.

## What this is

FatCatAM / NOD Academy portal ("DealFlow" repo). Supabase (Postgres + Edge
Functions + Storage) + Vercel (frontend). Owner: Dan Cruz (dancruzhomes@gmail.com).

- Repo: github.com/Dan8NOD/DealFlow
- Supabase project: iubxycckgrplbpdbncfk (https://iubxycckgrplbpdbncfk.supabase.co)
- Supabase dashboard: https://supabase.com/dashboard/project/iubxycckgrplbpdbncfk
- Edge Functions base: https://iubxycckgrplbpdbncfk.supabase.co/functions/v1/
- Frontend: Vercel (see https://vercel.com — connect the repo, auto-deploys on push)
- Login: dancruzhomes@gmail.com / Leads2025!

## Architecture (post-Render migration)

```
supabase/
  config.toml              # Supabase project config
  functions/               # Deno Edge Functions (replaces FastAPI routers)
    broker/                # $49/mo Stripe paywall → functions/v1/broker
    streets-submit/        # $100 challenge entries → functions/v1/streets-submit
    (add more as migrated)
backend/                   # legacy FastAPI — kept for local dev reference only
  app/                     # do NOT deploy this; use as reference for porting logic
```

The FastAPI backend in `backend/` is the reference implementation. Each router
(auth, dashboard, nod, trainer, calendly, fatcat, streets, broker) needs to be
ported to a Supabase Edge Function as needed. Broker and streets-submit are
done first (NOD-ify calls them). Port others as you need them.

## Edge Functions

Deploy a function:
```bash
cd ~/Documents/GitHub/DealFlow
supabase functions deploy broker --project-ref iubxycckgrplbpdbncfk
```

Set secrets (Stripe keys, etc.) in Supabase dashboard:
Settings → Edge Functions → Secrets, or:
```bash
supabase secrets set STRIPE_SECRET_KEY=... STRIPE_PRICE_ID=... --project-ref iubxycckgrplbpdbncfk
```

## Frontend (Vercel)

The DealFlow frontend lives in `static/` (or will be migrated there). Vercel
auto-deploys from `main` on push. Connect the repo at https://vercel.com.

## Hard rules (violating these breaks prod)

1. Prod DB = Supabase Postgres. Local dev DB = SQLite (legacy) or local
   Supabase (`supabase start`). NEVER use strftime/date()/GROUP_CONCAT/ifnull
   in raw SQL. Use SQLAlchemy funcs or branch on db dialect.
2. Auth: Supabase Auth (JWT via Supabase SDK). Legacy FastAPI auth in
   `backend/app/auth.py` is reference only.
3. Never commit .env files. Use `supabase secrets set` for prod, `.env.local`
   for dev.
4. New tables: create via Supabase migration (`supabase migration new`) or
   Supabase dashboard SQL editor.
5. Edge Functions are Deno (TypeScript), not Python. Port logic from the
   FastAPI routers but adapt to Deno runtime.
6. MixMatch.html on NOD-ify (GH Pages) calls the broker Edge Function. The URL
   is: https://iubxycckgrplbpdbncfk.supabase.co/functions/v1/broker

## Key features map (porting status)

- /api/broker/* → Edge Function `broker` (PORTED — NOD-ify calls it)
- /streets/submit → Edge Function `streets-submit` (PORTED)
- /dashboard — real estate SPA (needs porting to Vercel frontend)
- /nod — NOD Academy (needs porting)
- /products — product ladder + Stripe (needs porting)
- /calendly — coaching sessions (needs porting)
- /contact, /ad, /sell, /buy — lead capture (needs porting)

## How to make a change

1. Read the ONE file you're editing. Nothing else.
2. Shortest working diff. No new abstractions, deps, or "for later".
3. For Edge Functions: `supabase functions deploy <name> --project-ref iubxycckgrplbpdbncfk`
4. For frontend: push to main → Vercel auto-deploys ~30-60s
5. Verify: `python3 scripts/verify.py` (update base URL as needed) or curl the
   Edge Function directly.
6. Report: what changed, verify result, live URL. Three lines max.

## Env vars / secrets (Supabase dashboard, never in repo)

STRIPE_SECRET_KEY, STRIPE_PRICE_ID, STRIPE_WEBHOOK_SECRET, CALENDLY_API_KEY
Set via: `supabase secrets set KEY=value --project-ref iubxycckgrplbpdbncfk`

## If prod is broken

- Edge Function 500 → check Supabase dashboard → Logs → Edge Functions
- Frontend down → check Vercel dashboard → Deployments
- DB connection → Supabase dashboard → Database → Health
- CORS error → check function headers (Access-Control-Allow-Origin)

## Verify

```bash
# Health check
curl https://iubxycckgrplbpdbncfk.supabase.co/health

# Broker endpoint (NOD-ify calls this)
curl https://iubxycckgrplbpdbncfk.supabase.co/functions/v1/broker/verify \
  -H "Authorization: Bearer <token>"
```
