// Azure infrastructure for Renter Portal SaaS
// Run: az deployment group create --resource-group renter-portal-prod --template-file main.bicep --parameters dbAdminPassword=<pw> secretKey=<key>

@description('Azure region')
param location string = resourceGroup().location

@description('Environment name')
@allowed(['dev', 'staging', 'prod'])
param environment string = 'prod'

@description('Base name for all resources')
param baseName string = 'renterportal'

@description('Container image tag')
param imageTag string = 'latest'

@description('Database admin password')
@secure()
param dbAdminPassword string

@description('Secret key for JWT signing (32+ random chars)')
@secure()
param secretKey string

@description('Azure Container Registry name (must be globally unique)')
param acrName string = '${baseName}acr'

var dbAdminUsername    = 'renteradmin'
var appServicePlanName = '${baseName}-plan-${environment}'
var webAppName         = '${baseName}-api-${environment}'
var postgresServerName = '${baseName}-pg-${environment}'
var databaseName       = 'renter_portal'
var acrLoginServer     = '${acrName}.azurecr.io'
var acrImage           = '${acrLoginServer}/backend:${imageTag}'

// ── Container Registry ───────────────────────────────────────────────────────
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: {
    // NOTE: switch to Managed Identity after first deploy (adminUserEnabled: false)
    adminUserEnabled: true
  }
}

// ── App Service Plan (Linux) ──────────────────────────────────────────────────
resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: appServicePlanName
  location: location
  sku: { name: 'B1', tier: 'Basic' }
  kind: 'linux'
  properties: { reserved: true }
}

// ── PostgreSQL Flexible Server ────────────────────────────────────────────────
resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresServerName
  location: location
  sku: { name: 'Standard_B1ms', tier: 'Burstable' }
  properties: {
    administratorLogin: dbAdminUsername
    administratorLoginPassword: dbAdminPassword
    version: '16'
    storage: { storageSizeGB: 32 }
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgresServer
  name: databaseName
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

// Allow Azure-internal services (App Service → Postgres)
resource firewallAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgresServer
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

// ── Web App ───────────────────────────────────────────────────────────────────
resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  name: webAppName
  location: location
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'DOCKER|${acrImage}'
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'DOCKER_REGISTRY_SERVER_URL',      value: 'https://${acrLoginServer}' }
        { name: 'DOCKER_REGISTRY_SERVER_USERNAME', value: acr.listCredentials().username }
        { name: 'DOCKER_REGISTRY_SERVER_PASSWORD', value: acr.listCredentials().passwords[0].value }
        { name: 'WEBSITES_PORT',     value: '8000' }
        { name: 'ENVIRONMENT',       value: 'production' }
        { name: 'DEBUG',             value: 'false' }
        { name: 'SECRET_KEY',        value: secretKey }
        { name: 'DATABASE_URL',      value: 'postgresql://${dbAdminUsername}:${dbAdminPassword}@${postgresServer.properties.fullyQualifiedDomainName}:5432/${databaseName}?sslmode=require' }
        { name: 'BASE_URL',          value: 'https://${webAppName}.azurewebsites.net' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
      ]
    }
  }
}

// ── Application Insights ──────────────────────────────────────────────────────
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${baseName}-insights-${environment}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    RetentionInDays: 30
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────────
output webAppUrl      string = 'https://${webApp.defaultHostName}'
output acrLoginServer string = acrLoginServer
output postgresHost   string = postgresServer.properties.fullyQualifiedDomainName
output webAppName     string = webAppName
