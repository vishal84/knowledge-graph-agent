#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
PREFIX_FILTER="${1:-}"
FORCE_FLAG="${2:-}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Error: .env file not found at ${ENV_FILE}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

if [[ -z "${GOOGLE_CLOUD_PROJECT_NUMBER:-}" ]]; then
  echo "Error: GOOGLE_CLOUD_PROJECT_NUMBER is not set in ${ENV_FILE}" >&2
  exit 1
fi

ACCESS_TOKEN="$(gcloud auth print-access-token)"
LIST_URL="https://discoveryengine.googleapis.com/v1alpha/projects/${GOOGLE_CLOUD_PROJECT_NUMBER}/locations/global/authorizations"

RAW_JSON="$(curl -sS \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "x-goog-user-project: ${GOOGLE_CLOUD_PROJECT_NUMBER}" \
  "${LIST_URL}")"

AUTH_NAMES="$(python3 - <<'PY' "${RAW_JSON}" "${PREFIX_FILTER}"
import json
import sys

payload = json.loads(sys.argv[1])
prefix = sys.argv[2]

for auth in payload.get("authorizations", []):
    name = auth.get("name", "")
    if not name:
        continue
    short_name = name.rsplit('/', 1)[-1]
    if prefix and not short_name.startswith(prefix):
        continue
    print(name)
PY
)"

if [[ -z "${AUTH_NAMES}" ]]; then
  if [[ -n "${PREFIX_FILTER}" ]]; then
    echo "No authorizations found with prefix '${PREFIX_FILTER}'."
  else
    echo "No authorizations found."
  fi
  exit 0
fi

echo "Authorizations to delete:"
while IFS= read -r auth_name; do
  echo "- ${auth_name}"
done <<< "${AUTH_NAMES}"

if [[ "${FORCE_FLAG}" != "--force" ]]; then
  echo
  read -r -p "Delete all listed authorizations? [y/N] " reply
  if [[ ! "${reply}" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
  fi
fi

echo
while IFS= read -r auth_name; do
  echo "Deleting ${auth_name}"
  curl -sS -X DELETE \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -H "x-goog-user-project: ${GOOGLE_CLOUD_PROJECT_NUMBER}" \
    "https://discoveryengine.googleapis.com/v1alpha/${auth_name}"
  echo

done <<< "${AUTH_NAMES}"

echo "Done."
