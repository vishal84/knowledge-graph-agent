#!/bin/bash

PROJECT_ID=adk-mcp-sandbox
PROJECT_NUMBER=1081386014792
INSTANCE=adk-graph
DATABASE=people-graph

for SA in \
  "service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com" \
  "service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  "service-${PROJECT_NUMBER}@gcp-sa-aiplatform-vm.iam.gserviceaccount.com" \
  "${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
do
  # Less restrictive project-level binding (While in development)
  # gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  #   --member="serviceAccount:${SA}" \
  #   --role="roles/spanner.databaseUser"

  # More restrictive database-level binding (principal of least privilege)
  gcloud spanner databases add-iam-policy-binding "$DATABASE" \
    --instance="$INSTANCE" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:${SA}" \
    --role="roles/spanner.databaseUser" || true
done

# 3) verify project-level binding
gcloud projects get-iam-policy "$PROJECT_ID" \
  --format='flattened(bindings[].role,bindings[].members[])' \
  | grep -E 'roles/spanner.databaseUser|gcp-sa-aiplatform'