# Renter Portal — SaaS Architecture Plan

## Goal
Convert local Renter Portal into a multi-tenant SaaS product, deployed on Azure, ready for paid customers in ~12 months.

## Phased Roadmap

### Phase 1: Backend Scaffold (Week 1-2) ← STARTING HERE
- FastAPI app, SQLAlchemy models, JWT auth, multi-tenant schema
- SQLite for dev, PostgreSQL on Azure
- Migrate existing JSON data into seed/import script
- Docker + docker-compose for local dev

### Phase 2: Auth & Multi-tenant (Week 3-4)
- Email/password signup + email verification
- Magic-link login option
- Org/team model: each user belongs to an org
- Per-org data isolation (org_id on every row)
- Stripe billing integration (Free / Pro / Team tiers)

### Phase 3: Email Integrations (Week 5-8)
- Gmail API integration (OAuth, polling webhooks)
- Microsoft Graph API for Outlook
- IMAP fallback for other providers
- Replace Mail.app SQLite scripts with API-based ingestion

### Phase 4: Storage Integrations (Week 9-11)
- Google Drive API
- OneDrive / SharePoint (Microsoft Graph)
- Dropbox API
- S3 / Azure Blob for direct uploads

### Phase 5: Polish & Launch (Week 12+)
- Marketing site (landing page)
- Stripe self-serve signup
- Email support workflow
- Status page (statuspage.io)
- Analytics (PostHog or Plausible)

## Tech Stack

### Backend
- **FastAPI** — async Python, fast to build, great on Azure
- **SQLAlchemy 2.x** — ORM
- **PostgreSQL 16** — production DB (Azure Database for PostgreSQL)
- **SQLite** — local dev (no setup)
- **Alembic** — migrations
- **Pydantic v2** — settings + validation
- **python-jose** — JWT tokens
- **passlib[bcrypt]** — password hashing
- **httpx** — async HTTP for Gmail/Graph APIs

### Frontend
- **Server-rendered Jinja2 templates** — Phase 1-2 (simple, fast to build)
- **HTMX** — sprinkles of interactivity without a JS framework
- **Alpine.js** — small client-side reactivity
- Phase 4+: optionally migrate to React/Vue if needed

### Infrastructure (Azure)
- **Azure App Service** (Linux, Python 3.12) — FastAPI backend
- **Azure Database for PostgreSQL** (Flexible Server, Burstable B1ms) — DB
- **Azure Key Vault** — secrets
- **Azure Application Insights** — monitoring
- **Azure Static Web Apps** — marketing site (Phase 5)
- **Azure Container Registry** — Docker images
- **GitHub Actions** — CI/CD

### Email Integrations
- Gmail API (Google Identity Services)
- Microsoft Graph API (Outlook, Office 365)
- IMAP/SMTP fallback

## Data Model (Core Tables)

```
organizations (id, name, plan, created_at)
users (id, org_id, email, password_hash, role, created_at)
sessions (id, user_id, token, expires_at)
email_accounts (id, org_id, provider, credentials_json, last_sync_at)
properties (id, org_id, address, unit, status, rent, bedrooms, ...)
leads (id, org_id, name, email, phone, property_id, source, status, received_at)
applications (id, org_id, applicant_name, property_id, unit, status, handler, received_at)
application_events (id, application_id, event_type, occurred_at, source_email_id)
sales_deals (id, org_id, property_id, status, list_price, received_at)
cma_requests (id, org_id, property_id, kind, status, requested_at)
property_files (id, org_id, property_id, kind, path, source, name)
```

Every domain table has `org_id` for tenant isolation.

## Pricing Tiers

| Tier | Price | Leads/mo | Users | Email accounts |
|---|---|---|---|---|
| Free | $0 | 50 | 1 | 1 |
| Pro | $49/mo | Unlimited | 1 | 3 |
| Team | $149/mo | Unlimited | 10 | Unlimited |

## Local Dev Setup

```bash
# Clone
git clone <repo>
cd renter-portal

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload

# Frontend (Phase 1 is server-rendered, no build step)
# Open http://localhost:8000
```

## Azure Deploy (Phase 1)

```bash
# One-time setup
az login
az group create --name renter-portal-prod --location eastus

# Provision resources
cd deploy/infra
az deployment group create --resource-group renter-portal-prod --template-file main.bicep

# Deploy code
az containerregistry create --resource-group renter-portal-prod --name renterportal
docker build -t renterportal.azurecr.io/backend:latest .
docker push renterportal.azurecr.io/backend:latest

# App Service deploys from ACR
az webapp create --resource-group renter-portal-prod --plan renter-portal-plan --name renter-portal-api --deployment-container-image-name renterportal.azurecr.io/backend:latest
```

## Migration Path from Local

1. Take current `/Users/danielcruz/Desktop/Leads/` data and import as one org's seed data
2. Build a CLI tool `python -m app.cli import-local-data ~/Desktop/Leads/`
3. Once data is in DB, the web app reads from DB (not local files)
4. Email integrations replace the Mail.app SQLite parser
5. Cloud storage integrations replace iCloud Drive scanning

## Key Architectural Decisions

1. **Server-rendered over SPA** for Phase 1-3 — simpler, faster iteration, easier to maintain with limited engineering time
2. **PostgreSQL over NoSQL** — relational data with clear foreign keys
3. **JWT auth with refresh tokens** — stateless, works with multiple frontend hosts
4. **Multi-tenant by org_id column** — simpler than schema-per-tenant for this scale
5. **Background jobs via APScheduler or Azure Functions** — for email polling, file scanning
6. **Alembic migrations** — DB schema evolution without losing data

## What I'm NOT Building (out of scope for now)

- Mobile apps (responsive web only)
- Real-time sync (polling-based)
- Multi-currency / i18n (English only, USD)
- Custom domains per tenant (use Azure subdomain)
- Audit logs (Phase 4+)

## Recommended Tools

- **Cursor** or **VS Code + Codex** — for development (Codex is great, but Cursor is faster for AI pair-programming)
- **Azure CLI** — for cloud provisioning
- **Postman or Insomnia** — for API testing
- **GitHub** — for source control + CI/CD
- **Linear or Notion** — for project management
