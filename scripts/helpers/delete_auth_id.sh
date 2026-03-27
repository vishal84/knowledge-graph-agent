#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
FORCE_FLAG="${1:-}"

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
DELETE_URL="https://discoveryengine.googleapis.com/v1alpha/${AUTH_RESOURCE}"

echo "Deleting authorization resource: ${AUTH_RESOURCE}"

if [[ "${FORCE_FLAG}" != "--force" ]]; then
  read -p "This will delete the AUTH_ID authorization. Continue? (y/N) " -r
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deletion cancelled."
    exit 0
  fi
fi

echo "Sending DELETE request to ${DELETE_URL}..."

curl -sS -X DELETE \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "x-goog-user-project: ${GOOGLE_CLOUD_PROJECT_NUMBER}" \
  "${DELETE_URL}"

echo ""
echo "✅ Authorization resource ${AUTH_ID} deleted."
