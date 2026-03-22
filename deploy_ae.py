import os
import logging
from datetime import datetime
import vertexai
from vertexai import agent_engines
from vertexai.agent_engines import AdkApp
from agent_engine.agent import root_agent
from dotenv import load_dotenv, dotenv_values, set_key

def deploy():
  gcs_dir_name = f"knowledge-graph-agent-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

  local_agent = AdkApp(
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

  # Create on Agent Engine
  remote_app = client.agent_engines.create(
    agent=local_agent,
    config=dict(
      agent_framework="google-adk",
      display_name="Knowledge Graph Agent",
      description="An ADK agent that leverages a graph database hosted on Spanner.",
      staging_bucket=STAGING_BUCKET,
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
          "GOOGLE_CLOUD_PROJECT_NUMBER": GOOGLE_CLOUD_PROJECT_NUMBER,
          "GOOGLE_CLOUD_LOCATION": GOOGLE_CLOUD_LOCATION,
          "SPANNER_INSTANCE_ID": SPANNER_INSTANCE_ID,
          "SPANNER_DATABASE_ID": SPANNER_DATABASE_ID,
          "SPANNER_GRAPH_NAME": SPANNER_GRAPH_NAME,
          "SPANNER_DISABLE_BUILTIN_METRICS": SPANNER_DISABLE_BUILTIN_METRICS,
          "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY,
          "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT,
          "AUTH_ID": AUTH_ID,
          "CLIENT_ID": CLIENT_ID,
          "CLIENT_SECRET": CLIENT_SECRET
      }
    ),
  )

  # Print the agent engine ID, you will need it in the later steps to initialize
  # the ADK `VertexAiSessionService`.
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