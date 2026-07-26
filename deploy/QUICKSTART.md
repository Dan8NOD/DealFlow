# Deploy DealFlow — Quickstart (Supabase + Vercel)

## What you need

- Supabase account (free tier works) — https://supabase.com
- Vercel account (free tier works) — https://vercel.com
- GitHub repo: github.com/Dan8NOD/DealFlow (already exists)

## Step 1: Supabase project (already done)

- Project: iubxycckgrplbpdbncfk
- Dashboard: https://supabase.com/dashboard/project/iubxycckgrplbpdbncfk
- Postgres connection: postgresql://postgres:***@db.iubxycckgrplbpdbncfk.supabase.co:5432/postgres
- Edge Functions base URL: https://iubxycckgrplbpdbncfk.supabase.co/functions/v1/

## Step 2: Install Supabase CLI (5 min)

```bash
brew install supabase/tap/supabase
supabase login
```

## Step 3: Deploy Edge Functions (5 min)

Each function lives in `supabase/functions/<name>/index.ts`. Deploy:

```bash
cd ~/Documents/GitHub/DealFlow
supabase functions deploy broker --project-ref iubxycckgrplbpdbncfk
supabase functions deploy streets-submit --project-ref iubxycckgrplbpdbncfk
```

## Step 4: Set secrets (3 min)

```bash
supabase secrets set \
  STRIPE_SECRET_KEY=sk_... \
  STRIPE_PRICE_ID=price_... \
  STRIPE_WEBHOOK_SECRET=whsec_... \
  --project-ref iubxycckgrplbpdbncfk
```

Or set them in the dashboard: Settings → Edge Functions → Secrets.

## Step 5: Connect Vercel (5 min)

1. Go to https://vercel.com → New Project → import github.com/Dan8NOD/DealFlow
2. Framework preset: Other (static site) or Vite if you add a build step
3. Root directory: `/` (or `static/` if you move the frontend there)
4. Add env vars (Vercel dashboard → Settings → Environment Variables):
   - `NEXT_PUBLIC_SUPABASE_URL` = https://iubxycckgrplbpdbncfk.supabase.co
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY` = (from Supabase dashboard → Settings → API → anon key)
5. Deploy → live in ~60s at https://deal-flow-xxx.vercel.app

## Step 6: Custom domain (optional)

Vercel → Settings → Domains → add your domain → update DNS A/CNAME → SSL auto-issued.

**Total cost**: $0 (both free tiers). Upgrade when you have paying users.

## Step 7: Verify

```bash
curl https://iubxycckgrplbpdbncfk.supabase.co/functions/v1/broker/verify
```

Should return JSON. If 200, you're live.
