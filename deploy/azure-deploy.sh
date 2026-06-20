#!/bin/bash
# Provision Azure resources and deploy Renter Portal.
# Run ONCE after installing: brew install azure-cli docker
# Then: brew install --cask docker  (start Docker Desktop)
set -e

# ==== CONFIG ====
RESOURCE_GROUP="${RESOURCE_GROUP:-renter-portal-prod}"
LOCATION="${LOCATION:-eastus}"
ENVIRONMENT="${ENVIRONMENT:-prod}"
BASE_NAME="${BASE_NAME:-renterportal}"
ACR_NAME="${BASE_NAME}acr"
WEBAPP_NAME="${BASE_NAME}-api-${ENVIRONMENT}"

# ==== Secrets (prompt if not set as env vars) ====
if [ -z "$DB_ADMIN_PASSWORD" ]; then
    echo "Enter PostgreSQL admin password (min 8 chars, include uppercase+number+symbol):"
    read -s DB_ADMIN_PASSWORD
    echo
fi

if [ -z "$SECRET_KEY" ]; then
    echo "Generating random JWT secret key..."
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(40))")
    echo "Generated SECRET_KEY (save this somewhere safe — you need it if you redeploy):"
    echo "  $SECRET_KEY"
    echo
fi

# ==== 1. Login + create RG ====
echo "==> Logging in to Azure..."
az login --use-device-code
az account set --subscription "${SUBSCRIPTION_ID:-}"

echo "==> Creating resource group: $RESOURCE_GROUP in $LOCATION"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION"

# ==== 2. Deploy Bicep infrastructure ====
echo "==> Deploying infrastructure (5-10 min)..."
cd "$(dirname "$0")/infra"
az deployment group create \
    --resource-group "$RESOURCE_GROUP" \
    --template-file main.bicep \
    --parameters \
        environment="$ENVIRONMENT" \
        baseName="$BASE_NAME" \
        dbAdminPassword="$DB_ADMIN_PASSWORD" \
        secretKey="$SECRET_KEY" \
        imageTag="latest"

# ==== 3. Get outputs ====
ACR_SERVER=$(az deployment group show \
    --resource-group "$RESOURCE_GROUP" --name main \
    --query "properties.outputs.acrLoginServer.value" -o tsv)
PG_HOST=$(az deployment group show \
    --resource-group "$RESOURCE_GROUP" --name main \
    --query "properties.outputs.postgresHost.value" -o tsv)

echo ""
echo "==== INFRASTRUCTURE READY ===="
echo "ACR:      $ACR_SERVER"
echo "Postgres: $PG_HOST"
echo ""

# ==== 4. Build + push Docker image ====
echo "==> Building Docker image..."
cd "$(dirname "$0")/../backend"
az acr login --name "$ACR_NAME"
docker build -t "${ACR_SERVER}/backend:latest" .
docker push "${ACR_SERVER}/backend:latest"

# ==== 5. Update DATABASE_URL with real password ====
DB_URL="postgresql://renteradmin:${DB_ADMIN_PASSWORD}@${PG_HOST}:5432/renter_portal?sslmode=require"
az webapp config appsettings set \
    --resource-group "$RESOURCE_GROUP" \
    --name "$WEBAPP_NAME" \
    --settings "DATABASE_URL=${DB_URL}" > /dev/null

echo "==> Restarting web app..."
az webapp restart --resource-group "$RESOURCE_GROUP" --name "$WEBAPP_NAME"

# ==== 6. Wait for health check ====
echo "==> Waiting for app to start (up to 60s)..."
for i in $(seq 1 12); do
    sleep 5
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" "https://${WEBAPP_NAME}.azurewebsites.net/health" 2>/dev/null || echo "000")
    if [ "$STATUS" = "200" ]; then
        echo "==> App is live!"
        break
    fi
    echo "   ...waiting ($((i*5))s, status=$STATUS)"
done

echo ""
echo "==== DEPLOY COMPLETE ===="
echo "URL: https://${WEBAPP_NAME}.azurewebsites.net"
echo ""
echo "Next steps:"
echo "  1. Open the URL above and sign up with dancruzhomes@gmail.com"
echo "  2. Run the data import to seed your deals:"
echo "     python3 backend/import_xlsx.py"
echo "  3. Connect your Office 365 email at /auth/microsoft/start"
