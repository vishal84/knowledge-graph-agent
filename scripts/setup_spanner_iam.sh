#!/bin/bash

# Load .env from the repo root (one level up from scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
else
  echo "Warning: .env file not found at $ENV_FILE" >&2
fi

echo "GOOGLE_CLOUD_PROJECT: $GOOGLE_CLOUD_PROJECT"
echo "GOOGLE_CLOUD_PROJECT_NUMBER: $GOOGLE_CLOUD_PROJECT_NUMBER"
echo "SPANNER_INSTANCE_ID: $SPANNER_INSTANCE_ID"
echo "SPANNER_DATABASE_ID: $SPANNER_DATABASE_ID"

for SA in \
  "service-${GOOGLE_CLOUD_PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com" \
  "service-${GOOGLE_CLOUD_PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  "service-${GOOGLE_CLOUD_PROJECT_NUMBER}@gcp-sa-aiplatform-vm.iam.gserviceaccount.com" \
  "${GOOGLE_CLOUD_PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
do
  # Less restrictive project-level binding (While in development)
  # gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  #   --member="serviceAccount:${SA}" \
  #   --role="roles/spanner.databaseUser"

  # More restrictive database-level binding (principal of least privilege)
  gcloud spanner databases add-iam-policy-binding "$SPANNER_DATABASE_ID" \
    --instance="$SPANNER_INSTANCE_ID" \
    --project="$GOOGLE_CLOUD_PROJECT" \
    --member="serviceAccount:${SA}" \
    --role="roles/spanner.databaseUser" || true
done

# 3) verify project-level binding
gcloud projects get-iam-policy "$GOOGLE_CLOUD_PROJECT" \
  --format='flattened(bindings[].role,bindings[].members[])' \
  | grep -E 'roles/spanner.databaseUser|gcp-sa-aiplatform'