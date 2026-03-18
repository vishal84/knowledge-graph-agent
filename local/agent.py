import os
import logging
from pathlib import Path
from httplib2 import Credentials

from fastapi.openapi.models import OAuth2
from fastapi.openapi.models import OAuthFlowAuthorizationCode
from fastapi.openapi.models import OAuthFlows

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.agents.callback_context import CallbackContext

from google.adk.auth import AuthConfig, AuthCredential, AuthCredentialTypes, OAuth2Auth

from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

from dotenv import load_dotenv

# Load environment variables from the same directory as this file
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "MCP SERVER URL NOT SET")

# Define the OAuth2 authentication scheme for OpenID Connect with Google as the provider. The token returned
# by this flow will be used to provide the MCP server headers it can use to make authorization decisions based 
# on the authenticated user's identity and permissions. The scopes defined here specify the level of access the 
# token will have, including access to the user's email, profile, and cloud platform resources.

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
    auth_credential=auth_credential
)

def get_access_token(readonly_context: ReadonlyContext) -> str | None:

    if hasattr(readonly_context, "session") and hasattr(readonly_context.session, "state"):
        session_state = dict(readonly_context.session.state)
        logger.info(f"session state keys: {list(session_state.keys())}")
        
        for key, value in session_state.items():
            logger.info(f"Inspecting session state \n key: {key}, \n value: {value}, \n type: {type(value)}")

            # Check for AuthCredential object with OpenID Connect [:10]
            if isinstance(value, AuthCredential) and value.auth_type == AuthCredentialTypes.OPEN_ID_CONNECT and value.oauth2:
                if value.oauth2.access_token:
                    logger.info(f"\n\nFound access_token in AuthCredential object in session state key: \n   * key: {key} \n   * token: {value.oauth2.access_token}\n\n")
                    return value.oauth2.access_token

            # Direct string token check
            if isinstance(value, str) and (value.startswith("eyJ") or value.startswith("ya29.")):
                # Log only the beginning of the token for security
                logger.info(f"Found token in session state key: {key}, token: {value[:10]}...") 
                return value
            
            # Dictionary check for nested tokens (e.g., in case of a more complex session structure)
            if isinstance(value, dict):
                if "access_token" in value:
                    token = value["access_token"]
                    if isinstance(token, str) and (token.startswith("eyJ") or token.startswith("ya29.")):
                        logger.info(f"Found nested token in key: {key}, token: {token[:10]}...")
                        return token
                else:
                    # print dictionary keys
                    logger.info(f"Inspecting dict key '{key}': {list(value.keys())}")

    logger.info("No token found in session state.")
    return None

def mcp_header_provider(readonly_context: ReadonlyContext) -> dict[str, str]:
    token = get_access_token(readonly_context)

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
    auth_scheme=auth_scheme,
    auth_credential=auth_credential,
    errlog=mcp_logger
)

root_agent = LlmAgent(
    model="gemini-2.5-pro",
    name="code_snippet_auth_agent",
    instruction="""You are a helpful agent that has access to an MCP tool used to retrieve an end users information.
    - If a user asks what you can do, answer that you can provide information about them that the MCP server has access to such as their name, email, and profile picture.
    - Always use the MCP tool `get_user_info_from_access_token` to get user information, never make up user information on your own.
    """,
    tools=[cloud_run_mcp]
)
