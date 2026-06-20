# Deploy Renter Portal to Azure — Step by Step

Estimated time: 45–60 minutes, mostly waiting.
Cost: ~$35/month (B1 App Service + B1ms Postgres + Basic ACR).

---

## BEFORE YOU START — install 2 tools (10 min)

Open Terminal and run these one at a time:

```bash
# 1. Install Azure CLI
brew install azure-cli

# 2. Install Docker Desktop (downloads the app)
brew install --cask docker
```

Then open Docker Desktop from Applications and wait for it to say "Engine running".
You do NOT need to create a Docker account.

---

## STEP 1 — Log in to Azure (2 min)

```bash
az login
```

A browser window opens. Sign in with your Azure account (the one tied to your subscription).
If you don't have an Azure account yet: https://portal.azure.com → free trial, card required.

After login, confirm your subscription is active:
```bash
az account show --query "{name:name, id:id}" -o table
```

---

## STEP 2 — Run the deploy script (15–30 min)

```bash
cd /Users/danielcruz/Desktop/Leads/saas/deploy
chmod +x azure-deploy.sh
./azure-deploy.sh
```

It will:
- Ask you for a PostgreSQL password (make one up, save it — e.g. "Leads2025!Secure")
- Auto-generate a secure JWT secret key (it will print it — save it)
- Create all Azure resources (takes ~10 min)
- Build and push your Docker image (~5 min)
- Restart the app and health-check it

When done it prints: `URL: https://renterportal-api-prod.azurewebsites.net`

---

## STEP 3 — Seed your data (5 min)

The Azure app connects to a fresh PostgreSQL database. Import your deals:

```bash
cd /Users/danielcruz/Desktop/Leads/saas

# Set the production DATABASE_URL (get it from Step 2 output)
export DATABASE_URL="postgresql://renteradmin:YOUR_PW@YOUR_PG_HOST:5432/renter_portal?sslmode=require"

# Run the import (points at the live DB)
cd backend
python3 import_xlsx.py
python3 import_rented_applications.py
```

---

## STEP 4 — Create your account (2 min)

Go to: https://renterportal-api-prod.azurewebsites.net/signup

Sign up with:
- Email: dancruzhomes@gmail.com
- Password: anything 8+ chars

You'll land on your dashboard with all your properties, leads, and deals.

---

## STEP 5 — Connect Office 365 email (5 min)

This enables auto-sync of Westward360 application emails.

First, register the app in Azure AD:
1. Go to https://portal.azure.com → Azure Active Directory → App registrations → New registration
2. Name: "Renter Portal"
3. Redirect URI: https://renterportal-api-prod.azurewebsites.net/auth/microsoft/callback
4. After creating: go to "Certificates & secrets" → New client secret → copy it
5. Go to "API permissions" → Add → Microsoft Graph → Delegated → Mail.Read, User.Read, offline_access

Then add these to your App Service environment variables:
```bash
az webapp config appsettings set \
  --resource-group renter-portal-prod \
  --name renterportal-api-prod \
  --settings \
    MS_CLIENT_ID="<your-app-client-id>" \
    MS_CLIENT_SECRET="<your-client-secret>" \
    MS_REDIRECT_URI="https://renterportal-api-prod.azurewebsites.net/auth/microsoft/callback"
```

Then go to your dashboard → click "Connect Email" → sign in with dancruzhomes@gmail.com (Office 365).

---

## STEP 6 — Trigger first email sync (1 min)

```bash
curl -X POST https://renterportal-api-prod.azurewebsites.net/api/sync \
  -H "Cookie: session_token=YOUR_TOKEN"
```

Or just click "Sync Now" in the dashboard.

Your Westward360 application emails will flow in within minutes.

---

## COSTS

| Resource              | SKU          | Cost/mo  |
|-----------------------|--------------|----------|
| App Service           | B1 Linux     | ~$13     |
| PostgreSQL            | B1ms 32GB    | ~$15     |
| Container Registry    | Basic        | ~$5      |
| Application Insights  | Free tier    | $0       |
| **Total**             |              | **~$33** |

To pause costs when not in use:
```bash
az webapp stop --resource-group renter-portal-prod --name renterportal-api-prod
```

---

## IF ANYTHING BREAKS

Check logs:
```bash
az webapp log tail --resource-group renter-portal-prod --name renterportal-api-prod
```

Health check:
```bash
curl https://renterportal-api-prod.azurewebsites.net/health
```

---

## CUSTOM DOMAIN (optional, after it's working)

```bash
# Add your domain in Azure
az webapp config hostname add \
  --resource-group renter-portal-prod \
  --webapp-name renterportal-api-prod \
  --hostname portal.yourdomain.com

# Azure will give you a TXT record to add to your DNS
# SSL cert is auto-issued (free, Let's Encrypt)
```
