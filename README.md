# DealFlow — NOD-ify Sales Pipeline

A drag-and-drop sales pipeline board for NOD-ify products and services.
Pipeline -> Negotiation -> Closed.

Static HTML, no build step, no backend. Deploys on Vercel.
Data persists to localStorage (and Supabase when auth is configured).

## Product ladder

| Product | Price | Type | Source |
|---|---|---|---|
| Field Guide | $5 | Digital | Gumroad |
| Field Manual | $49 | Digital | Gumroad |
| Realtor Scripts | $99 | Digital | Gumroad |
| App Subscription | $5/mo | Subscription | Stripe (pending) |
| Coaching Hour | $500 | Service | Calendly |
| Training Day | $5,000 | Service | Email booking |

## Features

- Drag deals between Pipeline -> Negotiation -> Closed
- Add new deals with the + button
- Stats bar: total deals, pipeline value, closed revenue, MRR
- Filters by type (Digital / Subscriptions / Services)
- Dark/light theme toggle
- localStorage persistence (Supabase sync when configured)

## Deploy

```bash
git push origin main
# Vercel auto-deploys
```

## Local dev

Open `index.html` in a browser. No server needed.
