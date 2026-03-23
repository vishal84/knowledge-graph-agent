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
from google.genai.types import Part

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
SPANNER_GRAPH_NAME = os.getenv("SPANNER_GRAPH_NAME")
SPANNER_DISABLE_BUILTIN_METRICS = os.getenv("SPANNER_DISABLE_BUILTIN_METRICS")

USER_NAME_PLACEHOLDER = "user_name"

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


def _run_gql_query(query: str) -> dict:
    logger.info(f">>> 🛠️ Tool: Query sent to Spanner Graph:\n{query}")
    results = graph_store.query(query)
    if not results:
        return {"status": "success", "result": "Query returned no rows."}

    return {"status": "success", "result": json.dumps(results, indent=2)}

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

    if not SPANNER_GRAPH_NAME:
        return {
            "status": "error",
            "message": "Spanner graph name is not configured. Set SPANNER_GRAPH_NAME.",
        }

    normalized_query = query.strip()

    # Spanner GQL doesn't support Cypher's COLLECT().
    # Convert COLLECT(expr) to expr so generated queries remain executable.
    if re.search(r"\bCOLLECT\s*\(", normalized_query, flags=re.IGNORECASE):
        query = re.sub(
            r"\bCOLLECT\s*\(\s*([^)]+?)\s*\)",
            r"\1",
            normalized_query,
            flags=re.IGNORECASE,
        )
        normalized_query = query.strip()
        logger.info(
            "[Tool Execution] Rewrote unsupported COLLECT(...) expression for Spanner GQL."
        )

    # --- 1. Input Validation ---
    # Enforce that the query is a valid GQL query for this graph.
    # This provides a faster, clearer error to the LLM if it generates a bad query.
    valid_prefix_pattern = rf"^GRAPH\s+{re.escape(SPANNER_GRAPH_NAME)}\s+MATCH\b"
    if not re.match(valid_prefix_pattern, normalized_query, flags=re.IGNORECASE):
        # Allow MATCH-only queries by auto-prefixing the active graph.
        if re.match(r"^MATCH\b", normalized_query, flags=re.IGNORECASE):
            query = f"GRAPH {SPANNER_GRAPH_NAME} {normalized_query}"
            logger.info(
                "[Tool Execution] Auto-prefixed MATCH query with active graph name."
            )
        else:
            return {
                "status": "error",
                "message": f"Invalid GQL format. Query MUST start with 'GRAPH {SPANNER_GRAPH_NAME} MATCH ...'"
            }

    try:
        # --- 2. Query Execution ---
        # --- 3. Structured Result Formatting ---
        # Return results as a JSON string for better machine readability by the LLM.
        # This preserves the structure of the data (lists of dictionaries).
        return _run_gql_query(query)

    # --- 4. Specific Error Handling ---
    # Catch specific API errors for more granular feedback.
    except InvalidArgument as e:
        # This error often indicates a syntax problem in the GQL itself.
        details = str(e)
        if "Function not found: COLLECT" in details:
            return {
                "status": "error",
                "message": (
                    "GQL Syntax Error: COLLECT(...) is not supported in Spanner GQL. "
                    "Return scalar rows (for example s.skillName) and aggregate in the final response. "
                    f"Details: {details}"
                ),
            }
        return {
            "status": "error",
            "message": f"GQL Syntax Error: The query is malformed. Please check the GQL syntax. Details: {details}"
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

def execute_gql_for_current_user(query: str, tool_context: ToolContext) -> dict:
    """
    Runs a GQL query that is scoped to the signed-in user.
    The query must include the literal placeholder user_name,
    which will be replaced with the authenticated user's formatted name.
    """
    creds, message = _get_credentials_or_auth_request(
        tool_context,
        "To proceed, sign in with your Google account first."
    )
    logger.info(f"Credentials obtained: {creds}, Message: {message}")
    if message:
        tool_context.actions.skip_summarization = True
        return Part.from_text(text=message)
    
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
        
        user_name = user_info.get("name")
        logger.info(f">>> 🛠️ Tool: Extracted user name: {user_name}")

        if not user_name:
            return {
                "status": "error",
                "message": "Unable to retrieve user's formatted name.",
            }

        if USER_NAME_PLACEHOLDER not in query:
            return {
                "status": "error",
                "message": (
                    "For user-scoped queries, include the placeholder "
                    f"{USER_NAME_PLACEHOLDER} for formattedName."
                ),
            }

        safe_name = re.sub(r"'", r"\\'", user_name)
        resolved_query = query.replace(USER_NAME_PLACEHOLDER, safe_name)

        logger.info(f">>> 🛠️ Tool: Resolved GQL for current user:\n{resolved_query}")
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
Do NOT use COLLECT(...). It is not supported in Spanner GQL.
For one-to-many relationships (for example person -> skills), return scalar rows (like s.skillName) and summarize/aggregate in natural language after retrieval.
If a query fails, read the error, rewrite the GQL, and try again.

--- 4. WHO AM I ---
Self-referential queries MUST resolve identity first, then query graph data.
If a user asks about themselves (for example: "who am i?", or uses self-referential language), you MUST use the 'execute_gql_for_current_user' tool.
When querying by a user's name, include {USER_NAME_PLACEHOLDER} in the GQL predicate where formattedName is needed.
Map the userinfo name field to the graph field: Person.formattedName. 
If a query fails, read the error, rewrite the GQL, and try again. Do not provide a response when running a query again.

Example pattern for name-based self-referential query:
GRAPH {SPANNER_GRAPH_NAME} MATCH (p:Person) WHERE p.formattedName LIKE '%{USER_NAME_PLACEHOLDER}%' RETURN p
"""

root_agent = LlmAgent(
    model="gemini-2.5-pro",
    name="knowledge_graph_agent",
    instruction=system_prompt,
    tools=[execute_gql, execute_gql_for_current_user]
)
