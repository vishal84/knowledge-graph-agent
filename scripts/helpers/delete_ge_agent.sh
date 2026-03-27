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
  "AUTH_ID"
)

for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "Error: required environment variable ${var} is not set in ${ENV_FILE}" >&2
    exit 1
  fi
done

ACCESS_TOKEN="$(gcloud auth print-access-token)"
AUTH_RESOURCE="projects/${GOOGLE_CLOUD_PROJECT_NUMBER}/locations/global/authorizations/${AUTH_ID}"
BASE_URL="https://discoveryengine.googleapis.com/v1alpha/projects/${GOOGLE_CLOUD_PROJECT_NUMBER}/locations/global/collections/default_collection/engines/${GEMINI_ENTERPRISE_APP_ID}/assistants/default_assistant"

echo "Listing Gemini Enterprise assistant agents for app ${GEMINI_ENTERPRISE_APP_ID}..."

AGENTS_JSON="$(curl -sS \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "x-goog-user-project: ${GOOGLE_CLOUD_PROJECT_NUMBER}" \
  "${BASE_URL}/agents?pageSize=100")"

MATCHED_AGENTS="$(python3 - <<'PY' "${AGENTS_JSON}" "${AUTH_RESOURCE}"
import json
import sys

payload = json.loads(sys.argv[1])
auth_resource = sys.argv[2]

for agent in payload.get("agents", []):
    tool_auths = agent.get("authorizationConfig", {}).get("toolAuthorizations", [])
    if auth_resource in tool_auths:
        name = agent.get("name", "")
        display_name = agent.get("displayName", "")
        state = agent.get("state", "")
        engine = (
            agent.get("adkAgentDefinition", {})
            .get("provisionedReasoningEngine", {})
            .get("reasoningEngine", "")
        )
        print("\t".join([name, display_name, state, engine]))
PY
)"

if [[ -z "${MATCHED_AGENTS}" ]]; then
  echo "No assistant agents found using authorization ${AUTH_RESOURCE}."
  exit 0
fi

echo "Found assistant agents using ${AUTH_RESOURCE}:"
while IFS=$'\t' read -r name display_name state engine; do
  echo "- ${display_name:-<no display name>}"
  echo "  name: ${name}"
  echo "  state: ${state:-unknown}"
  if [[ -n "${engine}" ]]; then
    echo "  reasoning engine: ${engine}"
  fi
done <<< "${MATCHED_AGENTS}"

if [[ "${FORCE_DELETE}" != "--force" ]]; then
  echo
  read -r -p "Delete all of the agents listed above? [y/N] " reply
  if [[ ! "${reply}" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
  fi
fi

echo
echo "Deleting matched assistant agents..."
while IFS=$'\t' read -r name display_name state engine; do
  echo "Deleting ${name}"
  curl -sS -X DELETE \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -H "x-goog-user-project: ${GOOGLE_CLOUD_PROJECT_NUMBER}" \
    "https://discoveryengine.googleapis.com/v1alpha/${name}" >/dev/null
done <<< "${MATCHED_AGENTS}"

echo "Done."
