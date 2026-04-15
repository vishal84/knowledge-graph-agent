# Knowledge Graph Agent

An identity-aware AI agent built with the [Google Agent Development Kit (ADK)](https://google.github.io/adk-docs/) that queries a knowledge graph hosted on [Google Cloud Spanner](https://cloud.google.com/spanner). The agent uses an RDF/OWL ontology to understand the graph schema and generates [GQL](https://cloud.google.com/spanner/docs/graph/queries-overview) queries to answer natural language questions about people, skills, companies, certifications, and organizational relationships.

The agent supports **end-user authentication** — it resolves the signed-in user's identity so queries like _"who is my manager?"_ or _"what are my skills?"_ return personalized results.

## Table of Contents

1. [Repository Structure](#repository-structure)
2. [Prerequisites](#prerequisites)
3. [Python Environment Setup (uv)](#python-environment-setup-uv)
4. [Database Setup (Cloud Spanner)](#database-setup-cloud-spanner)
5. [Environment Configuration](#environment-configuration)
6. [Running Locally](#running-locally)
7. [Deploying to Agent Engine (Vertex AI)](#deploying-to-agent-engine-vertex-ai)
8. [Deploying to Cloud Run](#deploying-to-cloud-run)
9. [Registering with Gemini Enterprise](#registering-with-gemini-enterprise)
10. [Helper Scripts](#helper-scripts)
11. [Troubleshooting](#troubleshooting)

---

## Repository Structure

```
knowledge-graph-agent/
├── pyproject.toml                  # Project manifest — dependencies, build config (uv / hatch)
├── .env.example                    # Template for environment variables
├── deploy_agent_engine.py          # Programmatic Agent Engine deploy script (alternative to ADK CLI)
├── ontology_file.ttl               # RDF/OWL ontology defining graph schema for the LLM
├── local/                          # ── Local development agent ──
│   ├── __init__.py
│   ├── agent.py                    #   Agent definition (ADC auth, OAuth2 user identity)
│   ├── oauth_helper.py             #   OAuth2 helper for browser-based sign-in flow
│   └── ontology_compiler.py        #   Compiles TTL ontology into LLM-friendly markdown
├── agent_engine/                   # ── Vertex AI Agent Engine deployment ──
│   ├── __init__.py
│   ├── agent.py                    #   Agent definition (token injection, lazy schema loading)
│   ├── ontology_compiler.py        #   Ontology compiler (same as local)
│   ├── ontology_file.ttl           #   Ontology copy bundled for deployment
│   ├── requirements.txt            #   Agent Engine runtime dependencies
│   ├── create_auth_id.py           #   Register OAuth2 auth with Gemini Enterprise API
│   └── register_to_ge.py           #   Register deployed agent with Gemini Enterprise
├── cloud_run/                      # ── Cloud Run / A2A deployment ──
│   ├── __init__.py
│   ├── ontology_compiler.py        #   Ontology compiler (same as local)
│   ├── ontology_file.ttl           #   Ontology copy bundled for deployment
│   ├── requirements.txt            #   Cloud Run runtime dependencies (includes a2a-sdk)
│   ├── create_auth_id.py           #   Register OAuth2 auth (uses RUN_AUTH_ID)
│   ├── register_to_ge.py           #   Register A2A agent with Gemini Enterprise
│   └── knowledge_graph_agent/      #   ADK agent package served by Cloud Run
│       ├── __init__.py
│       ├── agent.py                #     Agent definition (A2A compatible)
│       └── agent.json              #     A2A agent card (protocol v1.0)
└── scripts/                        # ── Setup & teardown scripts ──
    ├── create_spanner_env.sh       #   Interactive Spanner instance + database creation
    ├── setup_spanner_iam.sh        #   Grant Spanner IAM permissions to AI Platform SAs
    ├── data/
    │   └── spanner_ddl.sql         #   DDL schema for the Spanner property graph
    └── helpers/
        ├── delete_all_auth_ids.sh  #   Bulk-delete Gemini Enterprise authorizations
        ├── delete_auth_id.sh       #   Delete a specific AUTH_ID authorization
        ├── delete_run_auth_id.sh   #   Delete a RUN_AUTH_ID authorization
        ├── delete_ge_agent.sh      #   Delete Agent Engine agents from Gemini Enterprise
        └── delete_cloud_run_ge_agent.sh  # Delete Cloud Run agents from Gemini Enterprise
```

### How the three deployment targets differ

| | **Local** (`local/`) | **Agent Engine** (`agent_engine/`) | **Cloud Run** (`cloud_run/`) |
|---|---|---|---|
| **Auth model** | Google ADC + OAuth2 browser flow | Token injection via `tool_context.state` | Token resolution via A2A context |
| **Schema loading** | Eager at startup | Lazy (avoids startup failures in serverless) | Lazy |
| **Use case** | Development & testing | Managed Vertex AI deployment | Containerized A2A microservice |
| **Identity resolution** | `oauth_helper.py` | Metadata server + auth token | `_resolve_access_token()` |

---

## Prerequisites

Before getting started you need:

1. **Google Cloud Project** with billing enabled. Note your **Project ID** and **Project Number**.
2. **gcloud CLI** installed and authenticated:
   ```bash
   gcloud auth login
   gcloud config set project <YOUR_PROJECT_ID>
   ```
3. **uv** — a fast Python package manager. Install it if you haven't:
   ```bash
   # macOS / Linux
   curl -LsSf https://astral.sh/uv/install.sh | sh

   # Or with Homebrew
   brew install uv
   ```
4. **Python 3.12+** (uv can install this for you — see next section).
5. **OAuth 2.0 Consent Screen & Credentials** configured in your GCP project (see [Environment Configuration](#environment-configuration) for details).

---

## Python Environment Setup (uv)

This project uses [uv](https://docs.astral.sh/uv/) for dependency management. The `pyproject.toml` at the repo root defines all dependencies.

### 1. Clone the repository

```bash
git clone <REPO_URL>
cd knowledge-graph-agent
```

### 2. Create a virtual environment and install dependencies

```bash
# Create a venv with Python 3.12+ and install all project dependencies
uv sync
```

This reads `pyproject.toml`, resolves dependencies, creates a `.venv/` directory, and installs everything — including `google-adk`, `google-cloud-spanner`, `langchain-google-spanner`, `rdflib`, and others.

### 3. Activate the environment (optional)

`uv run` automatically uses the project's virtual environment, so you don't need to activate it manually. But if you prefer:

```bash
source .venv/bin/activate
```

### 4. Verify the ADK CLI is available

```bash
uv run adk --help
```

You should see the ADK command-line help output. All commands in this guide use `uv run` to ensure they execute within the project environment.

---

## Database Setup (Cloud Spanner)

The agent queries a Spanner property graph. You need a Spanner instance, a database, and the DDL schema applied.

### Automated setup

An interactive script handles instance creation (free trial or paid), database creation, and DDL application:

```bash
chmod +x scripts/create_spanner_env.sh
./scripts/create_spanner_env.sh
```

The script will:
1. Check for an existing free trial Spanner instance
2. Attempt to create a free trial instance; fall back to a minimal paid instance if ineligible
3. Prompt you for a database name (with collision detection)
4. Optionally apply the DDL schema from `scripts/data/spanner_ddl.sql`

### IAM permissions

After creating the database, grant the AI Platform service accounts access so Agent Engine and Cloud Run can query Spanner:

```bash
chmod +x scripts/setup_spanner_iam.sh
./scripts/setup_spanner_iam.sh
```

This script reads your `.env` file and grants `roles/spanner.databaseUser` at the database level to the relevant service accounts.

### Verify

Check the [Cloud Spanner console](https://console.cloud.google.com/spanner) to confirm the instance, database, and graph (`TeamAgentGraph`) were created.

---

## Environment Configuration

### 1. Create your `.env` file

Copy the template and fill in your values:

```bash
cp .env.example .env
```

### 2. Required variables

```env
# Google Cloud
GOOGLE_CLOUD_PROJECT="your-project-id"
GOOGLE_CLOUD_PROJECT_NUMBER="123456789"
GOOGLE_CLOUD_LOCATION="us-central1"
GOOGLE_GENAI_USE_VERTEXAI=True

# Spanner
SPANNER_INSTANCE_ID="my-spanner-instance"
SPANNER_DATABASE_ID="my-database"
SPANNER_GRAPH_NAME="TeamAgentGraph"
SPANNER_ENABLE_METRICS=False

# OAuth2
CLIENT_ID="your-client-id.apps.googleusercontent.com"
CLIENT_SECRET="your-client-secret"
AUTH_ID="graph-agent-auth"

# Telemetry
GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=True
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=True
```

### 3. Setting up OAuth 2.0 credentials

1. In the [Google Cloud Console](https://console.cloud.google.com), go to **APIs & Services > OAuth consent screen**.
2. Select **Internal** (Google Workspace) or **External** and configure the consent screen.
3. Add scopes: `openid`, `auth/userinfo.email`, `auth/userinfo.profile`.
4. If external, add your email under **Test Users**.
5. Go to **APIs & Services > Credentials > Create Credentials > OAuth client ID**.
6. Select **Web application** and set the appropriate redirect URIs:
   - Local: `http://localhost:8080/dev-ui/...` (the ADK dev UI callback)
   - Agent Engine: `https://vertexaisearch.cloud.google.com/static/oauth/oauth.html`
7. Copy the **Client ID** and **Client Secret** into your `.env` file.

### 4. Additional variables for Cloud Run

If deploying to Cloud Run, also set:

```env
RUN_AUTH_ID="graph-agent-auth-run"
CLOUD_RUN_APP_URL="https://your-service-url.run.app"
```

---

## Running Locally

The local agent (`local/`) is designed for rapid development and testing. It uses Application Default Credentials for Spanner access and an OAuth2 browser flow for user identity.

### 1. Authenticate with GCP

```bash
gcloud auth application-default login
```

### 2. Start the ADK dev server

```bash
uv run adk web local/
```

This launches the ADK development UI at `http://localhost:8080`. You can:
- Chat with the agent in the browser
- Trigger the OAuth2 sign-in flow to test user-scoped queries
- Inspect tool calls, GQL queries, and agent reasoning

### How it works

1. The agent loads `ontology_file.ttl` and compiles it into a structured markdown summary that becomes part of the system prompt — this teaches the LLM about the graph schema (node types, edge types, properties, search strategies).
2. Two tools are exposed:
   - **`execute_gql()`** — Run a general GQL query against the Spanner graph
   - **`execute_gql_for_current_user()`** — Run a query scoped to the signed-in user (resolves identity via OAuth2 token → Google UserInfo API)
3. The agent auto-prefixes the graph name, validates GQL syntax, and rewrites `COLLECT()` expressions for Spanner compatibility.

---

## Deploying to Agent Engine (Vertex AI)

Agent Engine deploys the agent as a managed Vertex AI Reasoning Engine. There are two ways to deploy.

### Option A: ADK CLI (recommended)

```bash
uv run adk deploy agent_engine \
  --display_name "Knowledge Graph Agent" \
  --description "An ADK agent that leverages a graph hosted on Spanner." \
  --requirements_file ./agent_engine/requirements.txt \
  --env_file .env \
  ./agent_engine/
```

### Option B: Programmatic deploy script

The `deploy_agent_engine.py` script provides more control — it creates or **updates** an existing Agent Engine resource (using the `AGENT_ENGINE_ID` in your `.env` file):

```bash
uv run python deploy_agent_engine.py
```

What happens:
1. Reads the `.env` file for all configuration values
2. Initializes the Vertex AI client with your project and staging bucket
3. If `AGENT_ENGINE_ID` is set and valid, **updates** the existing engine; otherwise **creates** a new one
4. Writes the new `AGENT_ENGINE_ID` back to your `.env` file

### Prerequisites for Agent Engine

- A **GCS staging bucket** — set `STAGING_BUCKET` in your `.env` (e.g. `gs://my-bucket`)
- Spanner IAM permissions granted to the AI Platform service accounts (run `scripts/setup_spanner_iam.sh`)

---

## Deploying to Cloud Run

The Cloud Run deployment packages the agent as an [A2A (Agent-to-Agent)](https://google.github.io/A2A/) compatible service. The ADK CLI handles containerization and deployment — no Dockerfile is needed.

### Deploy

```bash
uv run adk deploy cloud_run \
  --project=<YOUR_PROJECT_ID> \
  --region=us-central1 \
  --service_name=knowledge-graph-agent \
  --app_name=knowledge_graph_agent \
  --with_ui \
  --a2a \
  ./cloud_run \
  -- \
  --env-vars-file=env.yaml \
  --service-account=<PROJECT_NUMBER>-compute@developer.gserviceaccount.com \
  --allow-unauthenticated
```

> **Note**: Arguments after `--` are passed directly to `gcloud run deploy`. Create an `env.yaml` with your environment variables in the format Cloud Run expects, or set them via the Cloud Run console.

### What you get

- An HTTPS endpoint serving the agent
- An A2A agent card at `/a2a/knowledge_graph_agent` describing the agent's capabilities
- (Optional) A built-in dev UI if `--with_ui` is specified

---

## Registering with Gemini Enterprise

After deploying to Agent Engine or Cloud Run, you can register the agent with Gemini Enterprise so it's accessible in the Gemini app.

### 1. Create an authorization ID

This registers your OAuth2 credentials with the Gemini Enterprise API:

```bash
# For Agent Engine
uv run python agent_engine/create_auth_id.py

# For Cloud Run
uv run python cloud_run/create_auth_id.py
```

### 2. Register the agent

```bash
# For Agent Engine
uv run python agent_engine/register_to_ge.py

# For Cloud Run
uv run python cloud_run/register_to_ge.py
```

---

## Helper Scripts

Utility scripts for managing deployed resources are in `scripts/helpers/`:

| Script | Purpose |
|---|---|
| `delete_auth_id.sh` | Delete the `AUTH_ID` authorization from Gemini Enterprise |
| `delete_run_auth_id.sh` | Delete the `RUN_AUTH_ID` authorization from Gemini Enterprise |
| `delete_all_auth_ids.sh` | Bulk-delete all (or filtered) authorizations |
| `delete_ge_agent.sh` | Delete Agent Engine agents from Gemini Enterprise |
| `delete_cloud_run_ge_agent.sh` | Delete Cloud Run agents from Gemini Enterprise |

Usage:
```bash
chmod +x scripts/helpers/*.sh
./scripts/helpers/delete_auth_id.sh
```

---

## Troubleshooting

### OAuth redirect URI mismatch

**Error**: `redirect_uri_mismatch` when signing in.

**Fix**: Ensure the redirect URI in the Google Cloud Console exactly matches the one your app uses. Check for trailing slashes, `http` vs `https`, and port numbers.

### Spanner queries return no data

- Verify the signed-in user's email exists in the Spanner graph as a `Person` node.
- Check that the service account has `roles/spanner.databaseUser` on the database.
- Confirm the `SPANNER_GRAPH_NAME` matches the graph defined in the DDL (`TeamAgentGraph`).

### Missing environment variables

The agent will fail to start if required `.env` variables are missing. Compare your `.env` against `.env.example` to ensure nothing is missing.

### Agent Engine deployment fails

- Ensure `STAGING_BUCKET` is set and the bucket exists.
- Run `scripts/setup_spanner_iam.sh` to grant the AI Platform service accounts Spanner access.
- Check that the `google-adk` version in `requirements.txt` matches `pyproject.toml`.

### Identity resolution

The agent resolves user identity by calling the Google UserInfo API with the OAuth2 access token. The returned `email` or `name` is matched against `Person` node properties in the graph. If your graph schema uses different property names, update the query logic in the relevant `agent.py`.
