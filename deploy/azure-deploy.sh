#!/bin/bash
# Provision Azure resources and deploy Renter Portal.
# Run once after creating a service principal.
set -e

# ==== CONFIG ====
RESOURCE_GROUP="${RESOURCE_GROUP:-renter-portal-prod}"
LOCATION="${LOCATION:-eastus}"
ENVIRONMENT="${ENVIRONMENT:-prod}"
BASE_NAME="${BASE_NAME:-renterportal}"
ACR_NAME="$BASE_NAME"  # must be globally unique

# ==== Load secrets (prompt if not set) ====
DB_ADMIN_PASSWORD="${DB_ADMIN_PASSWORD:-}"
if [ -z "$DB_ADMIN_PASSWORD" ]; then
    echo "Enter PostgreSQL admin password (will be stored in Azure Key Vault later):"
    read -s DB_ADMIN_PASSWORD
fi

SECRET_KEY="${SECRET_KEY:-}"
if [ -z "$SECRET_KEY" ]; then
    echo "Enter JWT secret key (32+ chars random):"
    read -s SECRET_KEY
fi

# ==== 1. Login + create RG ====
echo "==> Logging in to Azure..."
az login --use-device-code
az account set --subscription "${SUBSCRIPTION_ID:-}"

echo "==> Creating resource group..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION"

# ==== 2. Deploy Bicep ====
echo "==> Deploying infrastructure (this may take 5-10 minutes)..."
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

# Get outputs
WEBAPP_NAME=$(az deployment group show --resource-group "$RESOURCE_GROUP" --name main --query "properties.outputs.webAppUrl.value" -o tsv)
ACR_SERVER=$(az deployment group show --resource-group "$RESOURCE_GROUP" --name main --query "properties.outputs.acrLoginServer.value" -o tsv)
PG_HOST=$(az deployment group show --resource-group "$RESOURCE_GROUP" --name main --query "properties.outputs.postgresHost.value" -o tsv)

echo ""
echo "==== DEPLOYMENT COMPLETE ===="
echo "Web app URL: https://$WEBAPP_NAME"
echo "ACR login: $ACR_SERVER"
echo "Postgres host: $PG_HOST"
echo ""
echo "Next steps:"
echo "1. Build and push your Docker image:"
echo "   docker build -t $ACR_SERVER/backend:latest ./backend"
echo "   az acr login --name $ACR_NAME"
echo "   docker push $ACR_SERVER/backend:latest"
echo ""
echo "2. Set environment variables on the Web App:"
echo "   az webapp config appsettings set --resource-group $RESOURCE_GROUP --name renterportal-api-$ENVIRONMENT --settings DATABASE_URL=postgresql://renteradmin@$PG_HOST:5432/renter_portal SECRET_KEY='$SECRET_KEY'"
echo ""
echo "3. Restart the Web App:"
echo "   az webapp restart --resource-group $RESOURCE_GROUP --name renterportal-api-$ENVIRONMENT"
