# Deploy Renter Portal — Quickstart

You have: Office 365, can pay for Azure, **no Docker/Azure CLI/GitHub CLI installed**.

## Two paths — pick one

### Path A (RECOMMENDED): Render.com — live in 15 min, $0/mo to start
- No Docker needed, no Azure setup
- Free tier: Postgres + Web Service + Static site
- Push to GitHub → auto-deploy
- https://render.com

### Path B: Azure — full Bicep template ready, takes 2-4 hours
- $25-50/mo to start (B1 App Service + B1ms Postgres)
- Best long-term if you're committed to Azure

---

## Path A: Render.com (recommended for speed)

### Step 1: Install Homebrew tools (5 min)
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install gh postgresql@16
brew services start postgresql@16
```

### Step 2: Create GitHub repo and push (3 min)
```bash
cd /Users/danielcruz/Desktop/Leads/saas
git add -A
git commit -m "Initial SaaS scaffold"
gh auth login           # browser login
gh repo create renter-portal --public --source=. --remote=origin --push
```

### Step 3: Deploy on Render.com (5 min)
1. Go to https://dashboard.render.com
2. Click "New +" → "Web Service" → connect your `renter-portal` repo
3. Settings:
   - **Root Directory**: `backend`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables:
   - `DATABASE_URL` — from Render Postgres (auto-created)
   - `SECRET_KEY` — generate: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
   - `ENVIRONMENT` = `production`
   - `DEBUG` = `false`
5. Add a PostgreSQL database: "New +" → "PostgreSQL" → free tier
6. Copy the database URL into the web service's `DATABASE_URL`
7. Click "Create Web Service" → wait 5 min for first deploy
8. Visit `https://renter-portal-api-XXXX.onrender.com` — your app is LIVE

### Step 4 (optional): Custom domain
- Render → Settings → Custom Domain → add `portal.yourdomain.com`
- Update DNS CNAME → Render auto-issues Let's Encrypt cert

**Total cost to start**: $0 (free tier). When you have paying users, upgrade to $7/mo Starter.

---

## Path B: Azure (when ready to commit)

### Step 1: Install tools (10 min)
```bash
brew install azure-cli docker
# Then install Docker Desktop from docker.com
```

### Step 2: Login to Azure
```bash
az login
# Browser login, picks your subscription
```

### Step 3: Provision infrastructure (15-30 min)
```bash
cd /Users/danielcruz/Desktop/Leads/saas/deploy
chmod +x azure-deploy.sh
./azure-deploy.sh
# Will prompt for: DB admin password, JWT secret key
```

This creates:
- Resource Group `renter-portal-prod`
- Azure Container Registry
- App Service Plan (Linux, B1)
- Web App `renterportal-api-prod`
- PostgreSQL Flexible Server
- Application Insights

**Cost estimate**: ~$25-50/mo for B1 + B1ms Postgres + ACR.

### Step 4: Push code to GitHub (5 min)
```bash
cd /Users/danielcruz/Desktop/Leads/saas
gh auth login
git add -A
git commit -m "Initial Azure deploy"
gh repo create renter-portal --private --source=. --push
```

### Step 5: Set GitHub secrets (3 min)
Go to https://github.com/YOUR_USER/renter-portal/settings/secrets/actions and add:
- `AZURE_ACR_USERNAME` — from `az acr credential show --name renterportalacr`
- `AZURE_ACR_PASSWORD` — same
- `AZURE_WEBAPP_PUBLISH_PROFILE` — from `az webapp deployment list-publishing-profiles`
- `DATABASE_URL` — postgres connection string

### Step 6: Deploy
Push to `main` → GitHub Actions builds + pushes to Azure.

Visit `https://renterportal-api-prod.azurewebsites.net` — live!

---

## Which path to pick?

| Factor | Render.com (A) | Azure (B) |
|---|---|---|
| Time to live | 15 min | 2-4 hours |
| Cost to start | $0/mo | $25-50/mo |
| Cost at scale (1000 users) | $50-200/mo | $200-500/mo |
| Setup friction | Low | Medium-High |
| Long-term flexibility | Medium | High |
| Compliance / HIPAA | Limited | Full Azure compliance |

**My recommendation**: Start with Render.com. Get something live this week. Move to Azure later when you have paying customers and need the full Azure ecosystem.

---

## After deploying — what to do next

1. **Sign up** via your live URL
2. **Test the dashboard** — make sure tabs render
3. **Add Gmail/Outlook integration** (Phase 3 in ARCHITECTURE.md)
   - You have Office 365 → can use Microsoft Graph API
4. **Set up Stripe** for billing (Phase 2)
5. **Custom domain + landing page** (Phase 5)

---

## Need help with any specific step?

- I can write the GitHub Actions deploy.yml in more detail
- I can build the local data import CLI (move your 741 leads into the SaaS)
- I can add Gmail/Graph email integration scripts
- I can build Stripe billing + signup flow

Just tell me which path (A or B) and which step you're on.
