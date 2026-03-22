#!/bin/bash

PROJECT_ID=adk-mcp-sandbox
PROJECT_NUMBER=1081386014792
INSTANCE=adk-graph
DATABASE=people-graph

for SA in \
  "service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com" \
  "service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  "${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
do
  gcloud spanner databases add-iam-policy-binding "$DATABASE" \
    --instance="$INSTANCE" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:${SA}" \
    --role="roles/spanner.databaseUser" || true
done