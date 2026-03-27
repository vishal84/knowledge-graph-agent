#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
FORCE_DELETE="${1:-}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Error: .env file not found at ${ENV_FILE}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

required_vars=(
  "GOOGLE_CLOUD_PROJECT_NUMBER"
  "GEMINI_ENTERPRISE_APP_ID"
  "CLOUD_RUN_APP_URL"
)

for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "Error: required environment variable ${var} is not set in ${ENV_FILE}" >&2
    exit 1
  fi
done

ACCESS_TOKEN="$(gcloud auth print-access-token)"
BASE_URL="https://discoveryengine.googleapis.com/v1alpha/projects/${GOOGLE_CLOUD_PROJECT_NUMBER}/locations/global/collections/default_collection/engines/${GEMINI_ENTERPRISE_APP_ID}/assistants/default_assistant"

echo "Listing Gemini Enterprise assistant agents for app ${GEMINI_ENTERPRISE_APP_ID}..."

AGENTS_JSON="$(curl -sS \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "x-goog-user-project: ${GOOGLE_CLOUD_PROJECT_NUMBER}" \
  "${BASE_URL}/agents?pageSize=100")"

MATCHED_AGENTS="$(python3 - <<'PY' "${AGENTS_JSON}" "${CLOUD_RUN_APP_URL}"
import json
import sys

payload = json.loads(sys.argv[1])
cloud_run_url = sys.argv[2]

for agent in payload.get("agents", []):
    # Check if this is an A2A agent pointing to the Cloud Run URL
    a2a_def = agent.get("a2aAgentDefinition", {})
    if not a2a_def:
        continue
    
    agent_card_str = a2a_def.get("jsonAgentCard", "{}")
    try:
        agent_card = json.loads(agent_card_str)
    except:
        agent_card = {}
    
    provider_url = agent_card.get("provider", {}).get("url", "")
    
    if cloud_run_url in provider_url or cloud_run_url in agent_card.get("url", ""):
        name = agent.get("name", "")
        display_name = agent.get("displayName", "")
        state = agent.get("state", "")
        print("\t".join([name, display_name, state]))
PY
)"

if [[ -z "${MATCHED_AGENTS}" ]]; then
  echo "No assistant agents found pointing to ${CLOUD_RUN_APP_URL}."
  exit 0
fi

echo "Found assistant agents registered to ${CLOUD_RUN_APP_URL}:"
AGENT_NAMES=""
while IFS=$'\t' read -r name display_name state; do
  echo "- ${display_name:-<no display name>}"
  echo "  resource name: ${name}"
  echo "  state: ${state:-unknown}"
  AGENT_NAMES="${AGENT_NAMES}${name}"$'\n'
done <<< "${MATCHED_AGENTS}"

if [[ "${FORCE_DELETE}" != "--force" ]]; then
  read -p "Delete these agents? (y/N) " -r
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deletion cancelled."
    exit 0
  fi
fi

echo "Deleting agents..."
while IFS='' read -r agent_name; do
  [[ -z "${agent_name}" ]] && continue
  
  echo "Deleting ${agent_name}..."
  curl -sS -X DELETE \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -H "x-goog-user-project: ${GOOGLE_CLOUD_PROJECT_NUMBER}" \
    "${BASE_URL}/agents/${agent_name##*/}"
  
  echo "✅ Deleted ${agent_name}"
done <<< "${AGENT_NAMES}"

echo "All matched agents deleted."
