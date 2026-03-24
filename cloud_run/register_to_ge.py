import os
import logging
import json
import requests
import google.auth
import google.auth.transport.requests
from dotenv import load_dotenv, dotenv_values

def main():
    """
    Registers a Cloud Run-deployed ADK agent with Gemini Enterprise using the
    A2A (Agent-to-Agent) registration API.
    """
    # Configure logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger(__name__)

    # --- Agent Configuration ---
    AGENT_DISPLAY_NAME = "Knowledge Graph Agent"
    AGENT_DESCRIPTION = "An ADK agent that returns fictitious information from a people graph hosted on Spanner."
    AGENT_NAME = "knowledge-graph-agent"
    AGENT_PROVIDER_ORG = "adk-mcp-sandbox"

    # --- Environment Variables ---
    logger.info("Loading environment variables...")
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    load_dotenv(dotenv_path=env_path)
    env_vars = dotenv_values(dotenv_path=env_path)

    required_vars = [
        "CLOUD_RUN_APP_URL",
        "GEMINI_ENTERPRISE_APP_ID",
        "GOOGLE_CLOUD_PROJECT_NUMBER",
        "RUN_AUTH_ID",
    ]

    missing_vars = [var for var in required_vars if not env_vars.get(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return

    CLOUD_RUN_APP_URL = env_vars.get("CLOUD_RUN_APP_URL")
    GEMINI_ENTERPRISE_APP_ID = env_vars.get("GEMINI_ENTERPRISE_APP_ID")
    GOOGLE_CLOUD_PROJECT_NUMBER = env_vars.get("GOOGLE_CLOUD_PROJECT_NUMBER")
    RUN_AUTH_ID = env_vars.get("RUN_AUTH_ID")

    logger.info("Successfully loaded environment variables.")

    # IAM note: the Discovery Engine service account needs Cloud Run Invoker on the service.
    # Grant it once with:
    #   gcloud run services add-iam-policy-binding knowledge-graph-agent \
    #     --region=us-central1 \
    #     --member="serviceAccount:service-PROJECT_NUMBER@gcp-sa-discoveryengine.iam.gserviceaccount.com" \
    #     --role="roles/run.invoker"
    logger.info(
        "Reminder: ensure service-%s@gcp-sa-discoveryengine.iam.gserviceaccount.com "
        "has roles/run.invoker on the Cloud Run service.",
        GOOGLE_CLOUD_PROJECT_NUMBER,
    )

    # --- Registration Logic ---
    try:
        logger.info("Attempting to register agent with Gemini Enterprise...")

        credentials, _ = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        access_token = credentials.token

        api_url = (
            f"https://discoveryengine.googleapis.com/v1alpha/projects/{GOOGLE_CLOUD_PROJECT_NUMBER}/locations/global/"
            f"collections/default_collection/engines/{GEMINI_ENTERPRISE_APP_ID}/assistants/default_assistant/agents"
        )

        # jsonAgentCard must be a JSON-encoded string per the A2A registration spec.
        # The A2A endpoint is served at /a2a/{app_name} when deployed with --a2a.
        a2a_url = f"{CLOUD_RUN_APP_URL}/a2a/knowledge_graph_agent"
        agent_card = {
            "protocolVersion": "1.0",
            "url": a2a_url,
            "provider": {
                "organization": AGENT_PROVIDER_ORG,
                "url": CLOUD_RUN_APP_URL,
            },
            "name": AGENT_NAME,
            "description": AGENT_DESCRIPTION,
            "capabilities": {},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [
                {
                    "id": "graph_query",
                    "name": "Knowledge Graph Query",
                    "description": "Answer questions about people, skills, and teams from a Spanner graph.",
                    "examples": ["Who has Java skills?", "What team is Alice on?"],
                    "tags": ["graph", "spanner", "knowledge"],
                }
            ],
            "version": "1.0.0",
        }

        payload = {
            "name": AGENT_NAME,
            "displayName": AGENT_DISPLAY_NAME,
            "description": AGENT_DESCRIPTION,
            "a2aAgentDefinition": {
                "jsonAgentCard": json.dumps(agent_card),
            },
            "authorization_config": {
                "tool_authorizations": [
                    f"projects/{GOOGLE_CLOUD_PROJECT_NUMBER}/locations/global/authorizations/{RUN_AUTH_ID}"
                ]
            }
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "x-goog-user-project": GOOGLE_CLOUD_PROJECT_NUMBER,
        }

        response = requests.post(api_url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()

        logger.info("✅ Successfully registered agent to Gemini Enterprise!")
        logger.info(f"💬 Response: {response.json()}")

    except google.auth.exceptions.DefaultCredentialsError:
        logger.error("Authentication failed. Please run 'gcloud auth application-default login'.")
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error during registration: {e}")
        logger.error(f"Response body: {e.response.text}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()
