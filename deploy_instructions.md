# Deployment Guide: Azure App Service and Azure SQL Database

This guide explains how to set up the Azure resources, build and configure the Python application, and deploy it using two different methods:
1. **Direct Zip/Artifact Deployment**
2. **Containerized Deployment via Azure Container Registry (ACR)**

---

## Prerequisites
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) installed and authenticated (`az login`).
- A Python environment for local testing.
- Docker installed for container build testing (optional if using Azure-based builds).

---

## 1. Setup Azure SQL Database & Firewall

First, let's provision the Azure SQL Server and Database and allow connection.

### Define Variables (Bash / PowerShell)
```bash
# Variables
RESOURCE_GROUP="myAppResourceGroup"
LOCATION="eastus"
SQL_SERVER_NAME="visitors-sql-server-$RANDOM" # Must be globally unique
SQL_DATABASE_NAME="visitorsdb"
SQL_ADMIN_USER="dbadmin"
SQL_ADMIN_PASSWORD="ChooseAStrongPassword123!" # Change this!
APP_SERVICE_PLAN="visitors-app-plan"
WEB_APP_NAME="visitors-registry-app-$RANDOM"   # Must be globally unique
ACR_NAME="visitorsregistryacr$RANDOM"          # Must be globally unique, alphanumeric only
```

### Provision Resource Group & SQL Database
```bash
# 1. Create a Resource Group
az group create --name $RESOURCE_GROUP --location $LOCATION

# 2. Create Azure SQL Server
az sql server create \
    --name $SQL_SERVER_NAME \
    --resource-group $RESOURCE_GROUP \
    --location $LOCATION \
    --admin-user $SQL_ADMIN_USER \
    --admin-password $SQL_ADMIN_PASSWORD

# 3. Create Azure SQL Database
az sql db create \
    --resource-group $RESOURCE_GROUP \
    --server $SQL_SERVER_NAME \
    --name $SQL_DATABASE_NAME \
    --service-objective S0

# 4. Open Firewall to allow Azure Services (Crucial for App Service to connect)
az sql server firewall-rule create \
    --resource-group $RESOURCE_GROUP \
    --server $SQL_SERVER_NAME \
    --name "AllowAllWindowsAzureIps" \
    --start-ip-address "0.0.0.0" \
    --end-ip-address "0.0.0.0"

# 5. Open Firewall for your local IP (for local testing/setup)
# Replace with your actual public IP address
MY_IP=$(curl -s https://api.ipify.org)
az sql server firewall-rule create \
    --resource-group $RESOURCE_GROUP \
    --server $SQL_SERVER_NAME \
    --name "AllowLocalIP" \
    --start-ip-address $MY_IP \
    --end-ip-address $MY_IP
```

> [!IMPORTANT]
> The firewall rule `AllowAllWindowsAzureIps` with IP range `0.0.0.0` is required for Azure App Services to talk to Azure SQL Database. If you disable this, your application will receive a database connection error.

---

## Method A: Direct Zip/Artifact Deployment

This method bundles your Python files into a ZIP archive and deploys it directly to a Linux App Service. The App Service automatically detects the `requirements.txt` file and installs the dependencies on the server.

### 1. Create a Web App Service Plan & Web App
```bash
# Create App Service Plan (Linux)
az appservice plan create \
    --name $APP_SERVICE_PLAN \
    --resource-group $RESOURCE_GROUP \
    --location $LOCATION \
    --is-linux \
    --sku B1

# Create the Web App (Python 3.10 runtime)
az webapp create \
    --resource-group $RESOURCE_GROUP \
    --plan $APP_SERVICE_PLAN \
    --name $WEB_APP_NAME \
    --runtime "PYTHON:3.10"
```

### 2. Configure Database Environment Variables
Set the connection parameters so the Web App knows how to connect to Azure SQL:
```bash
az webapp config appsettings set \
    --resource-group $RESOURCE_GROUP \
    --name $WEB_APP_NAME \
    --settings \
    SQL_SERVER="$SQL_SERVER_NAME.database.windows.net" \
    SQL_DATABASE="$SQL_DATABASE_NAME" \
    SQL_USER="$SQL_ADMIN_USER" \
    SQL_PASSWORD="$SQL_ADMIN_PASSWORD" \
    SQL_ENCRYPT="yes" \
    SQL_TRUST_CERT="no"
```

### 3. Deploy the Code
You can deploy the directory directly using the Azure CLI `az webapp deploy` command:
```bash
# Zip the directory contents (exclude virtual env, git, etc. if present)
# Using zip command (Linux/macOS):
zip -r deployment.zip app.py db.py requirements.txt templates/

# Alternatively, deploy directly from the folder using az CLI:
az webapp deploy \
    --resource-group $RESOURCE_GROUP \
    --name $WEB_APP_NAME \
    --src-path deployment.zip \
    --type zip
```

> [!TIP]
> The Azure App Service environment for Python Linux pre-installs the SQL Server ODBC drivers, so `pyodbc` will automatically find and use the driver.

---

## Method B: Containerized Deployment (Docker + ACR)

This method packages the application and the required drivers into a Docker container, pushes it to Azure Container Registry (ACR), and configures Web App for Containers to run it.

### 1. Create Azure Container Registry (ACR)
```bash
# Create ACR
az acr create \
    --resource-group $RESOURCE_GROUP \
    --name $ACR_NAME \
    --sku Basic \
    --admin-enabled true
```

### 2. Build and Push Docker Image to ACR
You can build the image directly in the cloud using Azure Container Registry (no local Docker required!):
```bash
# Build image directly in ACR
az acr build \
    --registry $ACR_NAME \
    --image visitors-registry:latest .
```

### 3. Create Web App for Containers
```bash
# Get the ACR login server and username/password
ACR_LOGIN_SERVER=$(az acr show --name $ACR_NAME --query loginServer --output tsv)
ACR_CRED_USER=$(az acr credential show --name $ACR_NAME --query username --output tsv)
ACR_CRED_PASS=$(az acr credential show --name $ACR_NAME --query "passwords[0].value" --output tsv)

# Create App Service Plan for Container (Linux)
az appservice plan create \
    --name "${APP_SERVICE_PLAN}-docker" \
    --resource-group $RESOURCE_GROUP \
    --location $LOCATION \
    --is-linux \
    --sku B1

# Create the Web App for Containers
az webapp create \
    --resource-group $RESOURCE_GROUP \
    --plan "${APP_SERVICE_PLAN}-docker" \
    --name "${WEB_APP_NAME}-docker" \
    --container-image-name "$ACR_LOGIN_SERVER/visitors-registry:latest"
```

### 4. Configure App Settings & ACR Credentials
Set environment variables for the database and container registry credentials:
```bash
# Set registry credentials so App Service can pull the image
az webapp config container set \
    --resource-group $RESOURCE_GROUP \
    --name "${WEB_APP_NAME}-docker" \
    --docker-custom-image-name "$ACR_LOGIN_SERVER/visitors-registry:latest" \
    --docker-registry-server-url "https://$ACR_LOGIN_SERVER" \
    --docker-registry-server-user "$ACR_CRED_USER" \
    --docker-registry-server-password "$ACR_CRED_PASS"

# Set SQL database env variables
az webapp config appsettings set \
    --resource-group $RESOURCE_GROUP \
    --name "${WEB_APP_NAME}-docker" \
    --settings \
    SQL_SERVER="$SQL_SERVER_NAME.database.windows.net" \
    SQL_DATABASE="$SQL_DATABASE_NAME" \
    SQL_USER="$SQL_ADMIN_USER" \
    SQL_PASSWORD="$SQL_ADMIN_PASSWORD" \
    SQL_ENCRYPT="yes" \
    SQL_TRUST_CERT="no" \
    WEBSITES_PORT="8080"
```

> [!NOTE]
> The app setting `WEBSITES_PORT="8080"` tells Azure App Service that our container runs on port 8080 (which matches our Dockerfile exposure).

---

## 3. Verify Deployment

Once deployed, retrieve the URL of your Web Apps:
```bash
# Zip deployment URL
az webapp show --resource-group $RESOURCE_GROUP --name $WEB_APP_NAME --query defaultHostName --output tsv

# Container deployment URL
az webapp show --resource-group $RESOURCE_GROUP --name "${WEB_APP_NAME}-docker" --query defaultHostName --output tsv
```

Visit the URL in your browser. The application should load with a **Connected** badge, indicating it successfully connected to your Azure SQL Database and initialized the visitor table!
