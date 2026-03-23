import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import google.auth
import requests
from google.adk.agents import LlmAgent
from google.adk.tools import ToolContext
from google.adk.tools.base_tool import BaseTool
from google.api_core.exceptions import InvalidArgument
from google.cloud import spanner
from langchain_google_spanner import SpannerGraphStore

from .ontology_compiler import OntologyCompiler


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cloud Run supplies environment variables at runtime. Do not rely on a local
# .env file in this deploy-specific package.
AUTH_ID = os.getenv("AUTH_ID")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")

SPANNER_INSTANCE_ID = os.getenv("SPANNER_INSTANCE_ID")
SPANNER_DATABASE_ID = os.getenv("SPANNER_DATABASE_ID")
SPANNER_GRAPH_NAME = os.getenv("SPANNER_GRAPH_NAME")
SPANNER_DISABLE_BUILTIN_METRICS = os.getenv("SPANNER_DISABLE_BUILTIN_METRICS")

USER_NAME_PLACEHOLDER = "user_name"

graph_store: Optional[SpannerGraphStore] = None
physical_schema: Optional[str] = None


def dynamic_token_injection(tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext) -> Optional[Dict]:
    token_key = None
    pattern = re.compile(f"{AUTH_ID}.*") if AUTH_ID else None

    state_dict = tool_context.state.to_dict()
    if pattern is not None:
        matched_auth = {key: value for key, value in state_dict.items() if pattern.match(key)}
    else:
        matched_auth = {}

    if len(matched_auth) > 0:
        token_key = list(matched_auth.keys())[0]
    else:
        logger.info("No valid tokens found")
        return None

    access_token = tool_context.state[token_key]
    tool_context.state[AUTH_ID] = access_token
    logger.info("Token injected into tool context state under key '%s'", AUTH_ID)
    return None


ontology_compiler = OntologyCompiler(Path(__file__).resolve().parent / "ontology_file.ttl")
ontology_summary = ontology_compiler.compile_summary()


def _get_graph_store() -> SpannerGraphStore:
    global graph_store
    if graph_store is not None:
        return graph_store

    if SPANNER_DISABLE_BUILTIN_METRICS:
        os.environ["SPANNER_DISABLE_BUILTIN_METRICS"] = "true"

    credentials, _ = google.auth.default()
    spanner_client = spanner.Client(
        project=GOOGLE_CLOUD_PROJECT,
        credentials=credentials,
        disable_builtin_metrics=SPANNER_DISABLE_BUILTIN_METRICS,
    )

    graph_store = SpannerGraphStore(
        instance_id=SPANNER_INSTANCE_ID,
        database_id=SPANNER_DATABASE_ID,
        graph_name=SPANNER_GRAPH_NAME,
        client=spanner_client,
    )
    return graph_store


def _get_physical_schema() -> str:
    global physical_schema
    if physical_schema is not None:
        return physical_schema
    physical_schema = _get_graph_store().get_schema
    return physical_schema


def _run_gql_query(query: str) -> dict:
    logger.info(">>> Tool: Query sent to Spanner Graph:\n%s", query)
    results = _get_graph_store().query(query)
    if not results:
        return {"status": "success", "result": "Query returned no rows."}

    return {"status": "success", "result": json.dumps(results, indent=2)}


def execute_gql(query: str) -> dict:
    logger.info("\n[Tool Execution] Running GQL:\n%s\n", query)

    if not SPANNER_GRAPH_NAME:
        return {
            "status": "error",
            "message": "Spanner graph name is not configured. Set SPANNER_GRAPH_NAME.",
        }

    normalized_query = query.strip()

    if re.search(r"\bCOLLECT\s*\(", normalized_query, flags=re.IGNORECASE):
        query = re.sub(
            r"\bCOLLECT\s*\(\s*([^)]+?)\s*\)",
            r"\1",
            normalized_query,
            flags=re.IGNORECASE,
        )
        normalized_query = query.strip()
        logger.info("[Tool Execution] Rewrote unsupported COLLECT(...) expression for Spanner GQL.")

    valid_prefix_pattern = rf"^GRAPH\s+{re.escape(SPANNER_GRAPH_NAME)}\s+MATCH\b"
    if not re.match(valid_prefix_pattern, normalized_query, flags=re.IGNORECASE):
        if re.match(r"^MATCH\b", normalized_query, flags=re.IGNORECASE):
            query = f"GRAPH {SPANNER_GRAPH_NAME} {normalized_query}"
            logger.info("[Tool Execution] Auto-prefixed MATCH query with active graph name.")
        else:
            return {
                "status": "error",
                "message": f"Invalid GQL format. Query MUST start with 'GRAPH {SPANNER_GRAPH_NAME} MATCH ...'",
            }

    try:
        _get_physical_schema()
        return _run_gql_query(query)
    except InvalidArgument as exc:
        details = str(exc)
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
            "message": f"GQL Syntax Error: The query is malformed. Please check the GQL syntax. Details: {details}",
        }
    except Exception as exc:
        logger.error("An unexpected error occurred during GQL execution: %s", exc, exc_info=True)
        return {"status": "error", "message": f"An unexpected error occurred: {str(exc)}"}


def execute_gql_for_current_user(query: str, tool_context: ToolContext) -> dict:
    token = tool_context.state.get(AUTH_ID)
    userinfo_endpoint = "https://www.googleapis.com/oauth2/v3/userinfo"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = requests.get(userinfo_endpoint, headers=headers)
        response.raise_for_status()

        user_info = response.json()
        logger.info(">>> Tool: Successfully retrieved user info: %s", user_info)

        if not user_info:
            return {"status": "error", "message": "Unable to resolve user identity."}

        user_name = user_info.get("name")
        if not user_name:
            return {"status": "error", "message": "Unable to retrieve user's formatted name."}

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
        logger.info(">>> Tool: Resolved GQL for current user:\n%s", resolved_query)
        return execute_gql(resolved_query)
    except requests.RequestException as exc:
        logger.error(">>> Tool: Failed to retrieve user info: %s", exc)
        return {
            "status": "error",
            "message": f"Failed to retrieve user info: {str(exc)}",
        }


system_prompt = f"""
You are TeamAgent, an expert HR and Staffing assistant.
Your goal is to answer user questions by querying the Spanner Graph database using GQL.

--- 1. SEMANTIC UNDERSTANDING (ONTOLOGY) ---
{ontology_summary}

--- 2. PHYSICAL DATABASE SCHEMA ---
Schema is loaded lazily at runtime from Spanner to avoid deployment-time import failures.

--- 3. RULES FOR GQL ---
Always start queries with: GRAPH {SPANNER_GRAPH_NAME} MATCH ...
Use the 'execute_gql' tool to run your queries when a user is not querying their own data.
Do NOT use COLLECT(...). It is not supported in Spanner GQL.
For one-to-many relationships (for example person -> skills), return scalar rows (like s.skillName) and summarize/aggregate in natural language after retrieval.
If a query fails, read the error, rewrite the GQL, and try again.

--- 4. WHO AM I ---
Self-referential queries MUST resolve identity first, then query graph data.
If a user asks about themselves (for example: 'who am i?', or uses self-referential language), you MUST use the 'execute_gql_for_current_user' tool.
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
    tools=[execute_gql, execute_gql_for_current_user],
)