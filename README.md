# Knowledge Graph Agent

This repository contains two ADK agents:

- `local`: a local knowledge graph agent that answers questions by generating and executing Spanner GQL queries against a Google Cloud Spanner graph.
- `agent_engine`: an Agent Engine and Gemini Enterprise integration example that forwards end-user identity to an MCP server running on Cloud Run.

The primary runtime in this repo is the local knowledge graph agent. It uses ontology-aware prompting, a Spanner graph schema, and Google OAuth to answer both general graph questions and user-scoped questions such as "Who am I?" or "What skills do I have?"

## What The Local Agent Does

The local agent is defined in `local/agent.py` and exposes a single ADK `LlmAgent` named `knowledge_graph_agent`.

At startup it:

1. Loads configuration from the repository-level `.env` file.
2. Compiles the ontology in `ontology_file.ttl` into a concise prompt summary using `OntologyCompiler`.
3. Authenticates to Google Cloud with Application Default Credentials for Spanner access.
4. Connects to the configured Spanner graph through `langchain_google_spanner.SpannerGraphStore`.
5. Reads the graph schema and injects both ontology and schema into the system prompt.
6. Runs Gemini with two tools:
	- `execute_gql`
	- `execute_gql_for_current_user`

The result is an agent that can:

- answer general graph questions by generating Spanner GQL,
- validate and normalize generated GQL before execution,
- handle self-referential requests using end-user OAuth,
- resolve the signed-in user through the Google UserInfo API,
- substitute that user into the final GQL query before execution.

## Repository Layout

- `ontology_file.ttl`: ontology used to steer query generation.
- `local/agent.py`: local Spanner graph agent and its tools.
- `local/oauth_helper.py`: ADK OAuth helper for end-user sign-in.
- `local/ontology_compiler.py`: ontology-to-markdown prompt compiler.
- `agent_engine/agent.py`: Agent Engine example that injects end-user auth into an MCP tool call.
- `agent_engine/create_auth_id.py`: registers a Gemini Enterprise server-side OAuth authorization.
- `agent_engine/register_to_ge.py`: registers the deployed agent with Gemini Enterprise.
- `pyproject.toml`: Python package metadata and dependencies.

## Prerequisites

Before running the local agent, make sure you have:

- Python 3.12 or newer.
- `uv` installed.
- Access to a Google Cloud project with:
  - a Spanner instance,
  - a Spanner database,
  - a graph already created in that database,
  - an OAuth 2.0 client ID and client secret.
- Google Cloud Application Default Credentials configured locally.

For ADC, run:

```bash
gcloud auth application-default login
```

The agent uses ADC for server-side access to Spanner. End-user sign-in for self-scoped queries uses a separate OAuth flow described below.

## Environment Variables

Create a `.env` file in the repository root.

Minimum variables required for the local agent:

```env
GOOGLE_CLOUD_PROJECT=your-project-id
SPANNER_INSTANCE_ID=your-spanner-instance
SPANNER_DATABASE_ID=your-spanner-database
SPANNER_GRAPH_NAME=your-graph-name

CLIENT_ID=your-oauth-client-id.apps.googleusercontent.com
CLIENT_SECRET=your-oauth-client-secret

# Optional
SPANNER_DISABLE_BUILTIN_METRICS=true
```

Additional variables used by the Agent Engine and Gemini Enterprise example:

```env
AUTH_ID=user-info-auth
AUTH_URI=https://accounts.google.com/o/oauth2/auth
TOKEN_URI=https://oauth2.googleapis.com/token
GOOGLE_CLOUD_PROJECT_NUMBER=your-project-number
AGENT_ENGINE_ID=projects/PROJECT/locations/LOCATION/reasoningEngines/ID
GEMINI_ENTERPRISE_APP_ID=your-gemini-enterprise-app-id
MCP_SERVER_URL=https://your-cloud-run-mcp-service
```

## Google Cloud OAuth Setup

Create an OAuth 2.0 client in your Google Cloud project and configure the redirect URI used by the local ADK web UI:

```text
http://127.0.0.1:8000/dev-ui/
```

The local OAuth helper requests these scopes:

- `https://www.googleapis.com/auth/cloud-platform`
- `https://www.googleapis.com/auth/userinfo.email`
- `https://www.googleapis.com/auth/userinfo.profile`
- `openid`

Do not commit your `.env` file or client secret.

## How To Run The Local Agent

### 1. Install dependencies

From the repository root:

```bash
uv sync
```

### 2. Start the ADK web UI

From the repository root:

```bash
uv run adk web .
```

Why this command works:

- `adk web` expects an agents directory.
- the repository root contains agent subdirectories with `__init__.py` and `agent.py`.
- `local` is one of those agent directories.

Then open:

```text
http://127.0.0.1:8000
```

In the ADK UI, select the `local` agent.

### 3. Optional: run in terminal-only mode

If you want the interactive CLI instead of the web UI:

```bash
uv run adk run local
```

Use the web UI if you plan to test end-user OAuth, because the redirect URI in the code is tied to the local ADK web interface.

## How The Local Agent Answers Questions

The local agent uses a prompt built from three inputs:

1. Ontology summary from `ontology_file.ttl`
2. Physical schema from `SpannerGraphStore.get_schema`
3. Hard rules embedded in the system prompt in `local/agent.py`

Important prompt rules enforced by the agent:

- queries must target the configured Spanner graph,
- self-referential questions must use the user-scoped tool,
- `COLLECT(...)` must not be used because Spanner GQL does not support it,
- if a query fails, the model should rewrite and retry.

## Tool And Function Flow

### `execute_gql(query: str)`

This is the primary database execution tool for non-user-specific questions.

It performs the following work:

1. Verifies that `SPANNER_GRAPH_NAME` is configured.
2. Normalizes the query string.
3. Rewrites unsupported `COLLECT(...)` expressions into scalar output expressions.
4. Validates that the query starts with `GRAPH <graph_name> MATCH ...`.
5. Auto-prefixes the graph name if the model emits a bare `MATCH ...` query.
6. Executes the query through `_run_gql_query()`.
7. Returns structured JSON text or a detailed error.

Supporting function:

- `_run_gql_query(query: str)`: sends the final GQL to `graph_store.query()` and formats the rows as JSON.

### `execute_gql_for_current_user(query: str, tool_context: ToolContext)`

This tool handles self-referential questions such as:

- "Who am I?"
- "What skills do I have?"
- "What team am I on?"

It performs the following work:

1. Calls `_get_credentials_or_auth_request(...)`.
2. That helper calls `get_user_credentials(...)` in `local/oauth_helper.py`.
3. If the user is not signed in yet, ADK initiates the OAuth flow and the tool returns a pending sign-in message.
4. If credentials are available, the tool calls the Google UserInfo API:

	```text
	https://www.googleapis.com/oauth2/v3/userinfo
	```

5. It extracts the `name` field from the user profile.
6. It requires the generated query to contain the literal placeholder `user_name`.
7. It substitutes the signed-in user's display name into the GQL.
8. It delegates execution to `execute_gql(...)`.

This repo uses Spanner GQL, not GraphQL. When the code substitutes end-user identity into the query, it substitutes into a Spanner GQL statement before sending that statement to Spanner.

## How OAuth Works For End-User Context

The local end-user auth flow is implemented in `local/oauth_helper.py`.

### Credential lifecycle

`get_user_credentials(...)` checks credentials in this order:

1. Cached credentials from `tool_context.state`
2. Refresh of expired credentials if a refresh token exists
3. Pending auth response via `tool_context.get_auth_response(...)`
4. Fresh login prompt via `tool_context.request_credential(...)`

### ADK auth configuration

The helper builds an `AuthConfig` with:

- Google OAuth authorization endpoint
- Google token endpoint
- the local ADK redirect URI
- your `CLIENT_ID`
- your `CLIENT_SECRET`

It uses `raw_auth_credential` with an OpenID Connect credential, which matches current ADK expectations.

### Session storage

After a successful login, the helper converts the returned auth response into `google.oauth2.credentials.Credentials` and stores the serialized credential JSON in `tool_context.state` under the cache key `graph_creds`.

That means the user usually only needs to sign in once per session unless the token expires and cannot be refreshed.

## How UserInfo Is Applied To The Query

For end-user context, the agent prompt instructs the model to generate GQL using the placeholder `user_name` wherever the graph needs a person's formatted name.

Example pattern from the prompt:

```text
GRAPH <graph_name> MATCH (p:Person)
WHERE p.formattedName LIKE '%user_name%'
RETURN p
```

At runtime:

1. the user signs in,
2. `execute_gql_for_current_user(...)` calls the UserInfo API,
3. the code reads `user_info["name"]`,
4. the code escapes single quotes,
5. `user_name` is replaced with the authenticated user's formatted name,
6. the resolved query is sent to Spanner.

In other words, the end user's Google profile becomes the bridge between the OAuth login and the graph lookup on `Person.formattedName`.

## Example User Flows

### General graph question

User asks:

```text
Which people have Java skills?
```

Expected execution path:

- the model generates Spanner GQL,
- `execute_gql(...)` validates and runs it,
- the agent summarizes the returned rows.

### Self-referential question

User asks:

```text
What skills do I have?
```

Expected execution path:

- the model uses `execute_gql_for_current_user(...)`,
- ADK prompts the user to log in if needed,
- the tool fetches the user's profile from Google UserInfo,
- the placeholder `user_name` is replaced,
- the final Spanner GQL is executed,
- the agent responds with the signed-in user's graph data.

## Agent Engine And Gemini Enterprise Flow

The `agent_engine` folder contains a separate integration example.

That flow is different from the local Spanner graph agent:

- it uses an MCP toolset instead of direct Spanner access,
- it injects an end-user access token into MCP requests,
- it is intended for Agent Engine and Gemini Enterprise registration.

Key files:

- `agent_engine/create_auth_id.py`: creates a Gemini Enterprise authorization resource for server-side OAuth.
- `agent_engine/register_to_ge.py`: registers the provisioned reasoning engine as an agent in Gemini Enterprise.
- `agent_engine/agent.py`: injects end-user tokens into MCP calls through `dynamic_token_injection(...)` and `mcp_header_provider(...)`.

## Troubleshooting

### OAuth redirect does not complete

Check that your Google OAuth client includes:

```text
http://127.0.0.1:8000/dev-ui/
```

as an authorized redirect URI.

### Spanner query fails immediately

Check the following values in `.env`:

- `GOOGLE_CLOUD_PROJECT`
- `SPANNER_INSTANCE_ID`
- `SPANNER_DATABASE_ID`
- `SPANNER_GRAPH_NAME`

Also verify that your ADC identity has permission to query the Spanner database.

### End-user question does not resolve identity

The local tool expects the Google UserInfo API response to contain a `name` field. That value is mapped to `Person.formattedName` in the graph query.

If your graph stores identity under a different field or naming convention, update either:

- the query prompt instructions in `local/agent.py`, or
- the runtime substitution logic in `execute_gql_for_current_user(...)`.

### The model generates `COLLECT(...)`

Spanner GQL does not support `COLLECT(...)`. The tool attempts to rewrite it automatically, but the prompt already instructs the model to return scalar rows and aggregate in natural language instead.

## Development Notes

- The local agent loads `.env` from the repository root.
- Both the ontology and the physical schema are included directly in the system prompt.
- The self-referential path depends on Google OAuth and the UserInfo API, not on ADC.
- Spanner access itself depends on ADC, not the end-user OAuth token.

## Summary

This repo demonstrates a practical pattern for identity-aware graph querying:

- use ADC for backend access to Google Cloud Spanner,
- use ADK OAuth for end-user sign-in,
- call the Google UserInfo API after login,
- map the signed-in user's profile to a graph field,
- execute the resulting Spanner GQL with the local knowledge graph agent.
