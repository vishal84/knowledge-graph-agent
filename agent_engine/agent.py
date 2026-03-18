import os
import re
import json
import logging
from typing import Dict
from pathlib import Path
from typing import Optional, Any

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext

from google.adk.tools.tool_context import ToolContext
from google.adk.tools.base_tool import BaseTool

from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

from dotenv import load_dotenv

# Load environment variables from the parent directory as this file
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

AUTH_ID = os.getenv("AUTH_ID", "user-info-auth")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "MCP SERVER URL NOT SET")

# dynamic_auth_config is the parameter that will be injected into the tool call 
# arguments by the before_tool_callback function. The MCP tool implementation will look for this parameter and use it to authenticate to the MCP server using the end users credentials. The internal key "oauth2_auth_code_flow.access_token" is used to store the access token in the dynamic_auth_config dictionary, which is then serialized to a JSON string and passed as an argument in the tool call. The header provider can then extract the token from the dynamic_auth_config and use it to set the Authorization header when making requests to the MCP server.
DYNAMIC_AUTH_PARAM_NAME = "dynamic_auth_config" # Name of the parameter to inject
DYNAMIC_AUTH_INTERNAL_KEY = "oauth2_auth_code_flow.access_token" # Internal key for the token

# This function retrieves a token for authenticating to the Cloud Run service using the end users credentials via an auth_id 
# registered to Gemini Enterprise. The token is used in the Authorization header when making requests to the MCP 
# server running on Cloud Run to run tool calls as the end user.
def dynamic_token_injection(tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext) -> Optional[Dict]:
    token_key = None
    pattern = re.compile(f'' + AUTH_ID + '.*')

    state_dict = tool_context.state.to_dict()
    matched_auth = {key: value for key, value in state_dict.items() if pattern.match(key)}
    if len(matched_auth) > 0:
        token_key = list(matched_auth.keys())[0]
    else:
        logger.info("No valid tokens found")
        return None
    
    access_token = tool_context.state[token_key]
    tool_context.state[AUTH_ID] = access_token
    logger.info(f"Token injected into tool context state under key '{AUTH_ID}': {access_token}'")

    return None

def mcp_header_provider(readonly_context: ReadonlyContext) -> dict[str, str]:
    token = readonly_context.state.get(AUTH_ID)
    logger.info(f"Retrieved token for header injection: {token}")

    if not token:
        logger.info("No id_token or access_token found!")
        return {}
    
    return {
        "Authorization": f"Bearer {token.strip()}",
        "Accept": "application/json, text/event-stream",
        "Cache-Control": "no-cache"
    }

def mcp_logger(log_statement: str):
    logger.info(f"[McpToolset] {log_statement}", exc_info=True)

cloud_run_mcp = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=MCP_SERVER_URL,
    ),
    header_provider=mcp_header_provider,
    errlog=mcp_logger,
)

root_agent = LlmAgent(
    model="gemini-2.5-pro",
    name="code_snippet_agent",
    instruction="""You are a helpful agent that has access to an MCP tool used to retrieve an end users information.
    - If a user asks what you can do, answer that you can provide information about them that the MCP server has access to such as their name, email, and profile picture.
    - Always use the MCP tool `get_user_info_from_access_token` to get user information, never make up user information on your own.
    """,
    tools=[cloud_run_mcp],
    before_tool_callback=[dynamic_token_injection]
)
