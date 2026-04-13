# Project Setup and Deployment Guide

This repository contains an identity-aware AI agent that can be deployed in three different ways. This guide provides prescriptive, step-by-step instructions on how to configure your Google Cloud environment, set up the Spanner database, and deploy the application using any of the supported options.

## Table of Contents
1. [Deployment Options](#deployment-options)
2. [Prerequisites & Identity Setup](#prerequisites--identity-setup)
3. [Database Setup (Cloud Spanner)](#database-setup-cloud-spanner)
4. [Environment Configuration (.env files)](#environment-configuration-env-files)
5. [Troubleshooting & Development Notes](#troubleshooting--development-notes)

---

## Deployment Options

You can run or deploy this agent in three different environments. Depending on your choice, you will need to configure the specific folder associated with that option.

### 1. Running Locally
Ideal for development, testing, and rapid iteration.
*   **Folder**: The repository root (or top-level project directory).
*   **Instructions**: You will run the application server directly on your machine. It requires a connection to your Cloud Spanner instance in GCP.
*   **Commands**:
		*   **Node.js**:
				```bash
				npm install
				npm start
				```
		*   **Python**:
				```bash
				pip install -r requirements.txt
				python main.py
				```

### 2. Cloud Run
Deploy the agent as a containerized service on Google Cloud Run. This provides scale-to-zero capabilities and a public HTTPS URL.
*   **Folder**: `cloud_run/`
*   **Instructions**: Build a Docker image and deploy it to Cloud Run.
*   **Commands**:
		```bash
		cd cloud_run
		gcloud run deploy adk-agent \
			--source . \
			--platform managed \
			--region us-central1 \
			--allow-unauthenticated \
			--env-vars-file .env
		```
		*(Note: Adjust region and service name as needed. Ensure your `.env` file is present in the `cloud_run` directory or variables are set in GCP).*

### 3. Agent Engine
Deploy the agent using the dedicated "Agent Engine" framework (e.g., Vertex AI Agents).
*   **Folder**: `agent_engine/`
*   **Instructions**: Use the specific deployment commands required by the platform.
*   **Commands**:
		```bash
		cd agent_engine
		# Example command for Vertex AI Agents
		# gcloud beta ai agents create-deployment ...
		# Or follow project-specific instructions if a custom tool is used.
		```
		*(Note: Since the specific Agent Engine tool is not defined in this repo, confirm the correct command for your environment).*

---

## Prerequisites & Identity Setup

Before deploying or running the agent, you must set up your Google Cloud Project and configure End User Identity resolution. This is critical as the agent uses the signed-in user's identity to perform graph queries.

### 1. Google Cloud Project
Ensure you have a Google Cloud Project created. You will need the **Project ID** for all subsequent steps.

### 2. OAuth Consent Screen (End User Identity Setup)
To enable the application to identify the user running queries, you must set up OAuth 2.0 consent.

1.  In the Google Cloud Console, navigate to **APIS & Services** > **OAuth consent screen**.
2.  Select **User Type**:
		*   Choose **Internal** if you are in a Google Workspace organization and want to restrict access to users in your domain.
		*   Choose **External** for testing with any Google account.
3.  Click **Create**.
4.  **App Information**: Fill in the App name, User support email, and Developer contact information.
5.  **Scopes**: Click **Add or Remove Scopes**. You must add the following scopes to retrieve user profiles:
		*   `auth/userinfo.email`
		*   `auth/userinfo.profile`
		*   `openid`
6.  **Test Users**: If you selected "External" and the app is in "Testing" status, you *must* add the email addresses of any users (including yourself) who will test the app.
7.  Save and continue to complete the setup.

### 3. Register Client Credentials
After setting up the consent screen, you need to generate credentials to allow the application to authenticate with Google.

1.  Go to **APIS & Services** > **Credentials**.
2.  Click **Create Credentials** > **OAuth client ID**.
3.  Select **Web application** as the application type.
4.  **Name**: Enter a descriptive name (e.g., `Agent Local Client`).
5.  **Authorized JavaScript origins**:
		*   For local testing, add `http://localhost:<PORT>` (default port is often 8080).
		*   For Cloud Run, add your Cloud Run service URL.
6.  **Authorized redirect URIs**:
		*   Add the callback URL where Google will send the auth code.
		*   For local: `http://localhost:<PORT>/callback` (or the specific callback path your app uses).
		*   For Cloud Run: `https://your-cloud-run-url/callback`.
7.  Click **Create**.
8.  > [!IMPORTANT]
		> A dialog will appear showing your **Client ID** and **Client Secret**. Copy these values immediately. You will need them to populate the `.env` files in the next steps.

---

## Database Setup (Cloud Spanner)

This project requires a Cloud Spanner database instance to host the graph used by the agent. A script is provided in the `scripts/` folder to stage this database.

### Prerequisites
Ensure the user or service account running the script has the following IAM roles:
*   **Spanner Admin** (`roles/spanner.admin`) or **Owner** on the project to create instances and databases.

### Steps to Setup Spanner:

1.  Open your terminal and ensure you are authenticated with GCP and have selected the correct project:
		```bash
		gcloud auth login
		gcloud config set project <YOUR_PROJECT_ID>
		```
2.  Navigate to the repository root.
3.  Execute the setup script. This script will create a Spanner instance, a database, and apply the required DDL schema for the graph.

		```bash
		# Make the script executable
		chmod +x scripts/setup_spanner.sh

		# Run the script, passing your Project ID
		./scripts/setup_spanner.sh <YOUR_PROJECT_ID>
		```

4.  **Verify**: Check the Google Cloud Console under Spanner to ensure the instance and database (with tables) were created successfully.

---

## Environment Configuration (.env files)

To run or deploy the sample, you **must** create and populate a `.env` file in the folder corresponding to your chosen deployment option. The application relies on these variables to connect to Spanner and authenticate users.

### The .env Template

Create a `.env` file with the following structure:

```env
# Google Cloud Configuration
GCP_PROJECT_ID=your-gcp-project-id
SPANNER_INSTANCE_ID=your-spanner-instance-id
SPANNER_DATABASE_ID=your-spanner-database-id
SPANNER_GRAPH_NAME=your-spanner-graph-name

# OAuth Credentials for End User Identity
OAUTH_CLIENT_ID=your-oauth-client-id.apps.googleusercontent.com
OAUTH_CLIENT_SECRET=your-oauth-client-secret

# Application Settings
PORT=8080
```

### Where to put the .env files:

1.  **For Local Execution**:
		*   Place the `.env` file in the **root directory** of the repository.
2.  **For Cloud Run**:
		*   Place the `.env` file in the `cloud_run/` folder.
		*   *Alternative*: You can also set these variables directly in the Cloud Run Console under the service configuration instead of using a file.
3.  **For Agent Engine**:
		*   Place the `.env` file in the `agent_engine/` folder.

Fill in the values you gathered during the **Prerequisites** (OAuth Client ID/Secret) and **Database Setup** (Project ID, Spanner IDs).

---

## Running the Agent

Once configured, you can run the agent based on your deployment choice:

### Local
1. Ensure `.env` is in the root directory.
2. Run the start command:
	 ```bash
	 # For Node.js
	 npm start
	 
	 # For Python
	 python main.py
	 ```

### Cloud Run
1. Ensure `.env` is in the `cloud_run/` directory or variables are set in Cloud Run.
2. Deploy using the command shown in [Deployment Options](#2-cloud-run).
3. Access the service via the URL provided by Cloud Run.

### Agent Engine
1. Ensure `.env` is in the `agent_engine/` directory.
2. Run the specific deployment command or start command for your Agent Engine setup.

---

## Troubleshooting & Development Notes

### Identity Resolution
*   **Mapping**: The application expects the Google UserInfo API response to contain a `name` or `email` field to identify the user. This value is typically mapped to a specific node property in your Spanner graph (e.g., `Person.email` or `Person.formattedName`).
*   If your graph schema uses different field names, you may need to update the query logic in the source code to match your schema.

### Spanner Permissions
*   Ensure the account running the application (or the service account used by Cloud Run) has the **Spanner Database User** (`roles/spanner.databaseUser`) role or equivalent permissions to read/write to the database.

### Common Issues

*   **OAuth Redirect URI Mismatch**:
		*   *Error*: "Error: redirect_uri_mismatch" when signing in.
		*   *Solution*: Ensure the URL in your browser matches exactly what is registered in the GCP Console under "Authorized redirect URIs" for your Client ID. Check trailing slashes and HTTP vs HTTPS.
*   **Spanner Graph Queries Fail**:
		*   *Error*: No data returned or permission denied.
		*   *Solution*: Verify that the signed-in user's email exists in the Spanner graph as a node with the correct property mapping. Also verify the service account has permissions.
*   **Missing Environment Variables**:
		*   Ensure all variables in the `.env` file are populated correctly. Empty values or typos in variable names will cause connection failures.
