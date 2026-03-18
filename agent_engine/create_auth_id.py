import os
import logging
import json
import requests
import google.auth
import google.auth.transport.requests
from dotenv import load_dotenv, dotenv_values

def main():
    """
    Registers a deployed Agent Engine instance to a Gemini Enterprise App.
    """
    # Configure logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger(__name__)

    # --- Environment Variables ---
    logger.info("Loading environment variables...")
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    load_dotenv(dotenv_path=env_path)
    env_vars = dotenv_values(dotenv_path=env_path)

    required_vars = [
        "AUTH_ID",
        "CLIENT_ID",
        "CLIENT_SECRET",
        "AUTH_URI",
        "TOKEN_URI",
        "GOOGLE_CLOUD_PROJECT_NUMBER",
    ]

    missing_vars = [var for var in required_vars if not env_vars.get(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please add them to your .env file in the '2_agents' directory.")
        return

    AUTH_ID = env_vars.get("AUTH_ID")
    CLIENT_ID = env_vars.get("CLIENT_ID")
    CLIENT_SECRET = env_vars.get("CLIENT_SECRET")
    AUTH_URI = env_vars.get("AUTH_URI")
    TOKEN_URI = env_vars.get("TOKEN_URI")
    GOOGLE_CLOUD_PROJECT_NUMBER = env_vars.get("GOOGLE_CLOUD_PROJECT_NUMBER")

    logger.info("Successfully loaded environment variables.")

    # --- AUTH_ID Registration Logic ---
    try:
        logger.info("Attempting to register AUTH_ID with Gemini Enterprise...")

        # Get default credentials and project ID from the environment
        credentials, project = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        access_token = credentials.token

        api_url = (
            f"https://discoveryengine.googleapis.com/v1alpha/projects/{GOOGLE_CLOUD_PROJECT_NUMBER}/locations/global/"
            f"authorizations?authorizationId={AUTH_ID}"
        )

        payload = {
            "name": f"projects/{GOOGLE_CLOUD_PROJECT_NUMBER}/locations/global/authorizations/{AUTH_ID}",
            "serverSideOauth2": {
                "clientId": f"{CLIENT_ID}",
                "clientSecret": f"{CLIENT_SECRET}",
                "authorizationUri": f"{AUTH_URI}",
                "tokenUri": f"{TOKEN_URI}"
            }
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "x-goog-user-project": project,
        }

        response = requests.post(api_url, headers=headers, data=json.dumps(payload))
        response.raise_for_status() # Raise an exception for bad status codes

        logger.info("✅ Successfully registered AUTH_ID to Gemini Enterprise!")
        logger.info(f"💬 Response: {response.json()}")

    except google.auth.exceptions.DefaultCredentialsError:
        logger.error("Authentication failed. Please run 'gcloud auth application-default login'.")
    except requests.exceptions.HTTPError as e:
        logger.error(f"An HTTP error occurred during the API request: {e}")
        # Log the response body which often contains helpful error details
        logger.error(f"Response body: {e.response.text}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
