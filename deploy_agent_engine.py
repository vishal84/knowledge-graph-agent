import os
import logging
from datetime import datetime

import vertexai
from vertexai.agent_engines import AdkApp
from agent_engine.agent import root_agent
from dotenv import load_dotenv, dotenv_values, set_key


def _build_agent_engine_config(
  *,
  gcs_dir_name,
  staging_bucket,
  google_cloud_project_number,
  google_cloud_location,
  spanner_instance_id,
  spanner_database_id,
  spanner_graph_name,
  spanner_disable_builtin_metrics,
  google_cloud_agent_engine_enable_telemetry,
  otel_instrumentation_genai_capture_message_content,
  auth_id,
  client_id,
  client_secret,
):
  return dict(
    agent_framework="google-adk",
    display_name="Knowledge Graph Agent",
    description="An ADK agent that leverages a graph database hosted on Spanner.",
    staging_bucket=staging_bucket,
    # Use a unique staging prefix each deploy to avoid stale source reuse.
    gcs_dir_name=gcs_dir_name,
    extra_packages=["./agent_engine", "./agent_engine/ontology_file.ttl"],
    requirements=[
        "google-adk>=1.20.0",
        "python-dotenv>=1.0.0",
        "google-auth>=2.30.0",
        "google-cloud-spanner>=3.52.0",
        "rdflib",
        "langchain-google-spanner"
    ],
    env_vars={
        "GOOGLE_CLOUD_PROJECT_NUMBER": google_cloud_project_number,
        "GOOGLE_CLOUD_LOCATION": google_cloud_location,
        "SPANNER_INSTANCE_ID": spanner_instance_id,
        "SPANNER_DATABASE_ID": spanner_database_id,
        "SPANNER_GRAPH_NAME": spanner_graph_name,
        "SPANNER_DISABLE_BUILTIN_METRICS": spanner_disable_builtin_metrics,
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": google_cloud_agent_engine_enable_telemetry,
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": otel_instrumentation_genai_capture_message_content,
        "AUTH_ID": auth_id,
        "CLIENT_ID": client_id,
        "CLIENT_SECRET": client_secret
    }
  )


def _resolve_existing_agent_engine(client, agent_engine_id, logger):
  if not agent_engine_id:
    return None

  if "/reasoningEngines/" not in agent_engine_id:
    logger.warning("AGENT_ENGINE_ID is set but is not a valid reasoning engine resource name: %s", agent_engine_id)
    return None

  try:
    client.agent_engines.get(name=agent_engine_id)
    logger.info("Found existing Agent Engine resource: %s", agent_engine_id)
    return agent_engine_id
  except Exception as exc:
    logger.warning("AGENT_ENGINE_ID is set but could not be fetched. A new engine will be created. id=%s error=%s", agent_engine_id, exc)
    return None

def deploy():
  gcs_dir_name = f"knowledge-graph-agent-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

  deployment_app = AdkApp(
      agent=root_agent,
      enable_tracing=True,
  )

  # Configure logging
  logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
  logger = logging.getLogger(__name__)

  env_path = os.path.join(os.path.dirname(__file__), ".env")
  load_dotenv(dotenv_path=env_path)
  env_vars = dotenv_values(dotenv_path=env_path)

  GOOGLE_CLOUD_PROJECT=env_vars.get("GOOGLE_CLOUD_PROJECT")
  GOOGLE_CLOUD_PROJECT_NUMBER=env_vars.get("GOOGLE_CLOUD_PROJECT_NUMBER")
  GOOGLE_CLOUD_LOCATION=env_vars.get("GOOGLE_CLOUD_LOCATION")
  STAGING_BUCKET=env_vars.get("STAGING_BUCKET")
  SPANNER_INSTANCE_ID=env_vars.get("SPANNER_INSTANCE_ID")
  SPANNER_DATABASE_ID=env_vars.get("SPANNER_DATABASE_ID")
  SPANNER_GRAPH_NAME=env_vars.get("SPANNER_GRAPH_NAME")
  SPANNER_DISABLE_BUILTIN_METRICS=env_vars.get("SPANNER_DISABLE_BUILTIN_METRICS")
  GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=env_vars.get("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY")
  OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=env_vars.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT")
  AUTH_ID=env_vars.get("AUTH_ID")
  CLIENT_ID=env_vars.get("CLIENT_ID")
  CLIENT_SECRET=env_vars.get("CLIENT_SECRET")
  AGENT_ENGINE_ID=env_vars.get("AGENT_ENGINE_ID")

  logger.info("Initializing Vertex AI client with project: %s, location: %s, staging bucket: %s", GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, STAGING_BUCKET)

  vertexai.init(
    project=GOOGLE_CLOUD_PROJECT,
    location=GOOGLE_CLOUD_LOCATION,
    staging_bucket=STAGING_BUCKET
  )

  client = vertexai.Client(
    project=GOOGLE_CLOUD_PROJECT,
    location=GOOGLE_CLOUD_LOCATION,
  )

  config = _build_agent_engine_config(
    gcs_dir_name=gcs_dir_name,
    staging_bucket=STAGING_BUCKET,
    google_cloud_project_number=GOOGLE_CLOUD_PROJECT_NUMBER,
    google_cloud_location=GOOGLE_CLOUD_LOCATION,
    spanner_instance_id=SPANNER_INSTANCE_ID,
    spanner_database_id=SPANNER_DATABASE_ID,
    spanner_graph_name=SPANNER_GRAPH_NAME,
    spanner_disable_builtin_metrics=SPANNER_DISABLE_BUILTIN_METRICS,
    google_cloud_agent_engine_enable_telemetry=GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY,
    otel_instrumentation_genai_capture_message_content=OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT,
    auth_id=AUTH_ID,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
  )

  existing_agent_engine_id = _resolve_existing_agent_engine(
    client,
    AGENT_ENGINE_ID,
    logger,
  )

  if existing_agent_engine_id:
    logger.info("Updating existing Agent Engine: %s", existing_agent_engine_id)
    remote_app = client.agent_engines.update(
      name=existing_agent_engine_id,
      agent=deployment_app,
      config=config,
    )
  else:
    logger.info("Creating new Agent Engine deployment")
    remote_app = client.agent_engines.create(
      agent=deployment_app,
      config=config,
    )

  # Print the agent engine ID, update it in the .env file and log the deployment
  _agent_engine_id=remote_app.api_resource.name
  print(f"Agent Engine ID: {_agent_engine_id}")

  def update_env_file(agent_engine_id, env_file_path):
    """Updates the .env file with the agent engine ID."""
    try:
      set_key(env_file_path, "AGENT_ENGINE_ID", agent_engine_id)
      print(f"Updated AGENT_ENGINE_ID in {env_file_path} to {agent_engine_id}")
    except Exception as e:
      print(f"Error updating .env file: {e}")

  # log remote_app
  logging.info(
    f"Deployed agent to Vertex AI Agent Engine successfully, resource name: {_agent_engine_id}"
  )

  # Update the .env file with the new Agent Engine ID
  update_env_file(_agent_engine_id, env_path)

if __name__ == "__main__":
  deploy()