import os
import logging
import re
from pathlib import Path

from fastapi.openapi.models import OAuth2
from fastapi.openapi.models import OAuthFlowAuthorizationCode
from fastapi.openapi.models import OAuthFlows

from google.adk.agents import LlmAgent
from google.adk.tools import ToolContext

from google.adk.auth import AuthConfig, AuthCredential, AuthCredentialTypes, OAuth2Auth

import google.auth
from google.auth.credentials import Credentials
import google.auth.transport.requests

from .ontology_compiler import OntologyCompiler
from langchain_google_spanner import SpannerGraphStore
from google.cloud import spanner

import requests
from dotenv import load_dotenv

# Load environment variables from the same directory as this file
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

# Project Settings
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")

# Spanner Config
SPANNER_INSTANCE_ID = os.getenv("SPANNER_INSTANCE_ID")
SPANNER_DATABASE_ID = os.getenv("SPANNER_DATABASE_ID")
SPANNER_GRAPH_NAME = (os.getenv("SPANNER_GRAPH_NAME") or "").strip() or "TeamAgent"
SPANNER_DISABLE_BUILTIN_METRICS = os.getenv("SPANNER_DISABLE_BUILTIN_METRICS")

current_user_email = "user@example.com"
CURRENT_USER_EMAIL_PLACEHOLDER = f"{current_user_email}"

# ==========================================
# 2. SETUP ONTOLOGY & SCHEMA
# ==========================================
ontology_compiler = OntologyCompiler(Path(__file__).parent.parent / 'ontology_file.ttl')
ontology_summary = ontology_compiler.compile_summary()

# Get user credentails for Spanner access
credentials, _ = google.auth.default()
request = google.auth.transport.requests.Request()
credentials.refresh(request)
logger.info(f"Obtained access token for Spanner authentication: {credentials.get_cred_info}...")

if SPANNER_DISABLE_BUILTIN_METRICS:
    os.environ["SPANNER_DISABLE_BUILTIN_METRICS"] = "true"

spanner_client = spanner.Client(
    project=GOOGLE_CLOUD_PROJECT,
    credentials=credentials,
    disable_builtin_metrics=SPANNER_DISABLE_BUILTIN_METRICS,
)

# Connect to Spanner
graph_store = SpannerGraphStore(
    instance_id=SPANNER_INSTANCE_ID,
    database_id=SPANNER_DATABASE_ID,
    graph_name=SPANNER_GRAPH_NAME,
    client=spanner_client
)
physical_schema = graph_store.get_schema

# ==========================================
# 3. DEFINE THE TOOL
# ==========================================
def execute_gql(query: str) -> dict:
    """
    Executes a Spanner GQL query against the database.
    Input must be a valid GQL string starting with 'GRAPH TeamAgent MATCH...'.
    Returns the query results or an error message if the syntax is wrong.
    """
    print(f"\n[Tool Execution] Running GQL:\n{query}\n")
    try:
        results = graph_store.query(query)
        if not results:
            return {"status": "success", "result": "Query returned no rows."}

        output = [str(row) for row in results]
        return {"status": "success", "result": "\n".join(output)}

    except Exception as e:
        return {"status": "error", "message": f"GQL Error: {str(e)}"}
    
# ==========================================
# 4. DEFINE THE TOOL FOR USER INFO RETRIEVAL
# ==========================================
auth_scheme = OAuth2(
    flows=OAuthFlows(
        authorizationCode=OAuthFlowAuthorizationCode(
            authorizationUrl="https://accounts.google.com/o/oauth2/auth",
            tokenUrl="https://oauth2.googleapis.com/token",
            refreshUrl="https://oauth2.googleapis.com/token",
            scopes={
                "https://www.googleapis.com/auth/cloud-platform": "Cloud platform scope",
                "https://www.googleapis.com/auth/userinfo.email": "Email access scope",
                "https://www.googleapis.com/auth/userinfo.profile": "Profile access scope",
                "openid": "OpenID Connect scope",
            },
        )
    )
)

auth_credential = AuthCredential(
    auth_type=AuthCredentialTypes.OPEN_ID_CONNECT,
    oauth2=OAuth2Auth(
        client_id=CLIENT_ID, 
        client_secret=CLIENT_SECRET,
        redirect_uri="http://127.0.0.1:8000/dev-ui/",
    ),
)

auth_config = AuthConfig(
    auth_scheme=auth_scheme,
    raw_auth_credential=auth_credential,
)

def get_user_info(tool_context: ToolContext) -> dict | None:
    """
    Retrieves user information based on the access token in the session.
    Returns a dictionary with user info or None if no valid token is found.
    """
    auth_response = tool_context.get_auth_response(auth_config=auth_config)
    if not auth_response:
        tool_context.request_credential(auth_config=auth_config)
        return {
            "status": "auth_required",
            "message": "Please complete sign-in to continue.",
        }

    access_token = auth_response.oauth2.access_token if auth_response.oauth2 else None
    logger.info("Access token retrieved for user info.")
    
    if not access_token:
        logger.info("No access token found for get_user_info.")
        return None

    userinfo_endpoint = "https://www.googleapis.com/oauth2/v3/userinfo"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    try:
        response = requests.get(userinfo_endpoint, headers=headers)
        response.raise_for_status()
        
        user_info = response.json()
        logger.info(f">>> 🛠️ Tool: Successfully retrieved user info: {user_info}")
        return user_info
    except requests.RequestException as e:
        logger.error(f">>> 🛠️ Tool: Failed to retrieve user info: {str(e)}")
        return None

def execute_gql_for_current_user(query: str, tool_context: ToolContext) -> dict:
    """
    Runs a GQL query that is scoped to the signed-in user.
    The query must include the literal placeholder {current_user_email},
    which will be replaced with the authenticated user's email.
    """
    user_info = get_user_info(tool_context)
    if not user_info:
        return {
            "status": "error",
            "message": "Unable to resolve user identity.",
        }

    if user_info.get("status") == "auth_required":
        return user_info

    user_email = user_info.get("email")
    if not user_email:
        return {
            "status": "error",
            "message": "Authenticated user email was not returned by userinfo endpoint.",
        }

    if CURRENT_USER_EMAIL_PLACEHOLDER not in query:
        return {
            "status": "error",
            "message": (
                "For user-scoped queries, include the placeholder "
                f"{CURRENT_USER_EMAIL_PLACEHOLDER} in your GQL."
            ),
        }

    safe_email = re.sub(r"'", r"\\'", user_email)
    resolved_query = query.replace(CURRENT_USER_EMAIL_PLACEHOLDER, safe_email)
    return execute_gql(resolved_query)

system_prompt = f"""
You are TeamAgent, an expert HR and Staffing assistant.
Your goal is to answer user questions by querying the Spanner Graph database using GQL.


--- 1. SEMANTIC UNDERSTANDING (ONTOLOGY) ---
{ontology_summary}

--- 2. PHYSICAL DATABASE SCHEMA ---
{physical_schema}

--- 3. RULES FOR GQL ---
Always start queries with: GRAPH {SPANNER_GRAPH_NAME} MATCH ...
Use the 'execute_gql' tool to run your queries.
If a query fails, read the error, rewrite the GQL, and try again.

--- 4. WHO AM I ---
Self-referential queries MUST resolve identity first, then query graph data.
If a user asks about themselves (for example: "who am i", "me", "my", "myself", "I", "I'm", "mine", "my team"),
you MUST use 'execute_gql_for_current_user' instead of 'execute_gql'.
When using 'execute_gql_for_current_user', include {CURRENT_USER_EMAIL_PLACEHOLDER} in the GQL predicate where email is needed.
Map authenticated email to graph field: Person.cloudEmailAddress.
If a query fails, read the error, rewrite the GQL, and try again.

Example pattern:
GRAPH {SPANNER_GRAPH_NAME} MATCH (p:Person) WHERE p.cloudEmailAddress = '{CURRENT_USER_EMAIL_PLACEHOLDER}' RETURN p
"""

root_agent = LlmAgent(
    model="gemini-2.5-pro",
    name="knowledge_graph_agent",
    instruction=system_prompt,
    tools=[execute_gql, get_user_info, execute_gql_for_current_user]
)
