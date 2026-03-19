import os
import re
import json
import logging
import requests
from pathlib import Path
from typing import Tuple, Optional
from google.api_core.exceptions import InvalidArgument

from google.adk.agents import LlmAgent
from google.adk.tools import ToolContext
from google.adk.auth import AuthConfig

import google.auth
import google.auth.transport.requests
from google.oauth2.credentials import Credentials

from .ontology_compiler import OntologyCompiler
from .oauth_helper import get_user_credentials

from langchain_google_spanner import SpannerGraphStore
from google.cloud import spanner

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
logger.info(f"Obtained access token for Spanner authentication: {credentials.token}...")

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
    Input must be a valid GQL string.
    Returns the query results as a JSON string or an error message.
    """
    logger.info(f"\n[Tool Execution] Running GQL:\n{query}\n")

    # --- 1. Input Validation ---
    # Enforce that the query is a valid GQL query for this graph.
    # This provides a faster, clearer error to the LLM if it generates a bad query.
    if not query.strip().upper().startswith(f"GRAPH {SPANNER_GRAPH_NAME} MATCH"):
        return {
            "status": "error",
            "message": f"Invalid GQL format. Query MUST start with 'GRAPH {SPANNER_GRAPH_NAME} MATCH ...'"
        }

    try:
        # --- 2. Query Execution ---
        results = graph_store.query(query)
        if not results:
            return {"status": "success", "result": "Query returned no rows."}

        # --- 3. Structured Result Formatting ---
        # Return results as a JSON string for better machine readability by the LLM.
        # This preserves the structure of the data (lists of dictionaries).
        return {"status": "success", "result": json.dumps(results, indent=2)}

    # --- 4. Specific Error Handling ---
    # Catch specific API errors for more granular feedback.
    except InvalidArgument as e:
        # This error often indicates a syntax problem in the GQL itself.
        return {
            "status": "error",
            "message": f"GQL Syntax Error: The query is malformed. Please check the GQL syntax. Details: {str(e)}"
        }
    except Exception as e:
        # Catch-all for other unexpected database or connection errors.
        logger.error(f"An unexpected error occurred during GQL execution: {e}", exc_info=True)
        return {"status": "error", "message": f"An unexpected error occurred: {str(e)}"}
    
# ==========================================
# 4. DEFINE THE TOOL FOR USER INFO RETRIEVAL
# ==========================================
def _get_credentials_or_auth_request(
    tool_context: ToolContext, pending_message: str
) -> Tuple[Optional[Credentials], Optional[str]]:
    """
    A helper function to abstract the credential fetching logic.

    It checks for necessary environment variables and then calls get_user_credentials.
    It returns credentials on success, or an error/pending message on failure or if auth is needed.

    Args:
        tool_context: The context of the tool run.
        pending_message: The message to return if authentication is required.

    Returns:
        A tuple containing Credentials and an optional message.
        (Credentials, None) on success.
        (None, message) on failure or if auth is pending.
    """
    logger.info("Attempting to retrieve user credentials for authentication...")

    creds = get_user_credentials(
        tool_context=tool_context,
        credential_cache_key="graph_creds"
    )

    if isinstance(creds, AuthConfig) or creds is None:
        return None, pending_message
    
    return creds, None

def get_user_info(tool_context: ToolContext) -> dict | None:
    """
    Retrieves user information based on the access token in the session.
    Returns a dictionary with user info or None if no valid token is found.
    """
    creds, message = _get_credentials_or_auth_request(
        tool_context,
        "To proceed, sign in with your Google account first."
    )
    logger.info(f"Credentials obtained: {creds}, Message: {message}")

    if message:
        return message
    
    # At this point, we have valid credentials. Make the API call.
    userinfo_endpoint = "https://www.googleapis.com/oauth2/v3/userinfo"
    headers = {"Authorization": f"Bearer {creds.token}"}
    
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
    creds, message = _get_credentials_or_auth_request(
        tool_context,
        "To proceed, sign in with your Google account first."
    )
    logger.info(f"Credentials obtained: {creds}, Message: {message}")
    if message:
        return message
    
    # At this point, we have valid credentials. Make the API call.
    userinfo_endpoint = "https://www.googleapis.com/oauth2/v3/userinfo"
    headers = {"Authorization": f"Bearer {creds.token}"}
    
    try:
        response = requests.get(userinfo_endpoint, headers=headers)
        response.raise_for_status()
        
        user_info = response.json()
        logger.info(f">>> 🛠️ Tool: Successfully retrieved user info: {user_info}")

        if not user_info:
            return {
                "status": "error",
                "message": "Unable to resolve user identity.",
            }
    
        logger.info(f">>> 🛠️ Tool: Retrieved user info: {json.dumps(user_info)}")
        
        user_email = user_info["email"] if "email" in user_info else None

        if not user_email:
            return {
                "status": "error",
                "message": "Unable to retrieve user's email address.",
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

    except requests.RequestException as e:
        logger.error(f">>> 🛠️ Tool: Failed to retrieve user info: {str(e)}")
        return None

system_prompt = f"""
You are TeamAgent, an expert HR and Staffing assistant.
Your goal is to answer user questions by querying the Spanner Graph database using GQL.


--- 1. SEMANTIC UNDERSTANDING (ONTOLOGY) ---
{ontology_summary}

--- 2. PHYSICAL DATABASE SCHEMA ---
{physical_schema}

--- 3. RULES FOR GQL ---
Always start queries with: GRAPH {SPANNER_GRAPH_NAME} MATCH ...
Use the 'execute_gql' tool to run your queries when a user is not querying their own data.
If a query fails, read the error, rewrite the GQL, and try again.

--- 4. WHO AM I ---
Self-referential queries MUST resolve identity first, then query graph data.
If a user asks about themselves (for example: "who am i?", or uses self-referential language), you MUST use the 'execute_gql_for_current_user' tool.
When using 'execute_gql_for_current_user', include {CURRENT_USER_EMAIL_PLACEHOLDER} in the GQL predicate where email is needed.
Map authenticated email to graph field: Person.cloudEmailAddress.
If a query fails, read the error, rewrite the GQL, and try again. Do not provide a response when running a query again.

Example pattern for self-referential query:
GRAPH {SPANNER_GRAPH_NAME} MATCH (p:Person) WHERE p.cloudEmailAddress = '{CURRENT_USER_EMAIL_PLACEHOLDER}' RETURN p
"""

root_agent = LlmAgent(
    model="gemini-2.5-pro",
    name="knowledge_graph_agent",
    instruction=system_prompt,
    tools=[execute_gql, get_user_info, execute_gql_for_current_user]
)
