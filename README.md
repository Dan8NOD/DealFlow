# Renter Portal — SaaS

Multi-tenant SaaS for property managers and real estate agents. Tracks rental leads, applications, sales deals, CMA requests, and property files in one dashboard.

## Status

✅ **Phase 1 (Backend Scaffold)** — done
- FastAPI backend with multi-tenant schema
- Auth (email/password + JWT)
- Dashboard with Applications / Sales / CMAs tabs
- Docker + docker-compose for local dev
- Azure Bicep template for one-click provisioning
- GitHub Actions for CI/CD

⏳ **Phase 2 (Billing + Auth polish)** — TODO
⏳ **Phase 3 (Gmail + Outlook API integration)** — TODO
⏳ **Phase 4 (Google Drive + OneDrive integration)** — TODO
⏳ **Phase 5 (Marketing site + Stripe self-serve)** — TODO

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full plan.

## Local Development (Docker)

```bash
git clone <this-repo>
cd renter-portal-saas
cp backend/.env.example backend/.env

# Edit backend/.env with real values
# DATABASE_URL=postgresql://postgres:postgres@db:5432/renter_portal

docker-compose up --build
# Open http://localhost:8000
```

## Local Development (without Docker)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
pip install -r requirements.txt

# Use SQLite for fastest setup (no Docker needed)
export DATABASE_URL=sqlite:///./renter_portal.db
export SECRET_KEY=any-32-char-random-string

uvicorn app.main:app --reload
# Open http://localhost:8000
```

## Project Structure

```
saas/
├── ARCHITECTURE.md         # Full SaaS plan (5 phases)
├── README.md               # This file
├── docker-compose.yml      # Postgres + API for local dev
├── backend/
│   ├── Dockerfile          # Production container image
│   ├── requirements.txt
│   ├── .env.example
│   └── app/
│       ├── main.py         # FastAPI entry
│       ├── config.py       # Pydantic settings
│       ├── db.py           # SQLAlchemy engine/session
│       ├── models.py       # ORM models (multi-tenant)
│       ├── auth.py         # JWT + bcrypt
│       ├── routers/        # API routes
│       │   ├── auth.py     # /auth/signup, /auth/login
│       │   └── dashboard.py
│       └── templates/      # Jinja2 server-rendered UI
├── deploy/
│   ├── azure-deploy.sh     # One-command Azure provisioning
│   └── infra/
│       └── main.bicep      # Bicep template (ACR, App Service, Postgres, Insights)
└── .github/
    └── workflows/
        └── deploy.yml      # CI/CD to Azure on push to main
```

## Deploy to Azure

### Prerequisites
- Azure CLI installed (`brew install azure-cli`)
- Logged in (`az login`)
- Docker installed for building images

### One-time setup

```bash
# Create a service principal for GitHub Actions
az ad sp create-for-rbac \
    --name "renter-portal-github" \
    --role contributor \
    --scopes /subscriptions/<SUBSCRIPTION_ID> \
    --sdk-auth

# Save the JSON output as AZURE_CREDENTIALS secret in GitHub
# Also save: AZURE_ACR_USERNAME, AZURE_ACR_PASSWORD, AZURE_WEBAPP_PUBLISH_PROFILE, DATABASE_URL
```

### Deploy infrastructure

```bash
cd deploy
chmod +x azure-deploy.sh
./azure-deploy.sh
```

This creates:
- Resource Group
- Azure Container Registry
- App Service Plan (Linux, B1)
- Web App (FastAPI container)
- PostgreSQL Flexible Server (B1ms, 32GB)
- Application Insights

### Push code via GitHub Actions

After the first deploy, push to `main` branch and the workflow at `.github/workflows/deploy.yml` will:
1. Build Docker image
2. Push to ACR
3. Deploy to Web App
4. Update connection strings

## Data Model

Multi-tenant by `org_id`. Every domain table has `org_id` foreign key to `organizations.id`. Enforced via SQLAlchemy queries.

| Table | Purpose |
|---|---|
| organizations | Tenants (one per real estate company) |
| users | Login accounts, role (owner/admin/member) |
| properties | Rental/sale listings with status |
| leads | New inquiries from Zillow/Trulia/etc |
| applications | Application pipeline with events |
| sales_deals | Active/closed sales |
| cma_requests | CMA requests needing comp report |
| property_files | Linked documents (Drive, OneDrive) |

## Pricing Tiers

| Tier | Price | Limits |
|---|---|---|
| Free | $0 | 50 leads/mo, 1 user |
| Pro | $49/mo | Unlimited leads, 3 email accounts |
| Team | $149/mo | Unlimited users, unlimited emails |

## API Endpoints (current)

```
POST /auth/signup          Create org + user
POST /auth/login           Login (sets cookie)
POST /auth/logout          Clear cookie
GET  /                     Landing page
GET  /login                Login page
GET  /signup               Signup page
GET  /dashboard            Authenticated dashboard
GET  /api/dashboard.json   JSON stats for charts
GET  /health               Health check
```

## Phase 3 Plan: Email Integrations

Currently the SaaS scaffold is data-model-only — no email ingestion. To run in production:

1. **Gmail API** — Google Cloud project + OAuth flow
   - Watch for new messages via Pub/Sub webhook
   - Apply property-matching rules from local scripts
   - Insert into `leads`, `applications`, etc. tables

2. **Microsoft Graph API** (Outlook / Office 365)
   - Similar webhook subscription
   - One OAuth flow per org

3. **IMAP polling** (fallback)
   - APScheduler job every 5 min per connected account

## Roadmap to SaaS Launch (12 months)

- **Months 1-2**: Backend scaffold + billing (this is done; billing is next)
- **Months 3-4**: Gmail + Outlook integrations + landing page
- **Months 5-6**: Drive + OneDrive integrations
- **Months 7-9**: Polish, support flow, mobile responsive
- **Months 10-12**: Marketing site, analytics, public launch

## Tools Recommended

- **Cursor** or **VS Code + Codex** for editing
- **Postman** or **Insomnia** for API testing
- **Stripe** for billing (Phase 2)
- **Linear** for issue tracking

## Migration Path from Local

The current `/Users/danielcruz/Desktop/Leads/` data can be imported as a single org's seed data via a CLI tool we'll build in Phase 1.5:

```bash
python -m app.cli import-local-data /Users/danielcruz/Desktop/Leads/
```

This reads:
- `applications_data.json` → `applications` + `application_events`
- `sales_deals_data.json` → `sales_deals`
- `cma_dimitris_data.json` → `cma_requests`
- `portal_data.json` → `properties` + `leads`
- `property_files_data.json` → `property_files`

After import, the web app reads from DB and the local scripts can be retired.
