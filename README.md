# DealFlow — FatCat Pipeline

A drag-and-drop sales pipeline board for FatCat Asset Management.
Pipeline -> Showing -> Negotiation -> Closed.

Static HTML, no build step, no backend. Deploys on Vercel.
Reads from Supabase when auth is configured; falls back to local JSON.

## What's here

- `index.html` — the pipeline board (single file, no dependencies)
- `deals_data.json` — local fallback data (spreadsheet export format)
- `vercel.json` — cache headers

## What's NOT here (intentionally removed)

- The old FastAPI backend (3,000+ lines of Python) — superseded by Supabase
- The Stripe/broker integration — dead (0 subscribers, webhook verification
  commented out, NOD-ify uses a Supabase Edge Function instead)
- All Jinja2 templates, SQLAlchemy models, auth routers, Calendly integration

## Pipeline stages

| Stage | Description | Old spreadsheet statuses |
|---|---|---|
| Pipeline | Active listings & leads | EXECUTE, LIVE, Load Pics, Get Listing Agmt, YouTube/FB |
| Showing | Tours booked, CMAs in review | CMA |
| Negotiation | Offers, approvals, applicants | FOR APPROVAL, APPROVED APPLICANT |
| Closed | Signed, paid, done | FINISHED, CLOSED section |

## Deploy

```bash
git push origin main
# Vercel auto-deploys from main
```

## Local dev

Open `index.html` in a browser. That's it. No server needed.
