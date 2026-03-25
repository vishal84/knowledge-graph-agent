#!/bin/bash

# Exit immediately if a standard command fails
set -e

# Configuration variables
INSTANCE_ID="my-spanner-instance"
REGION_CONFIG="regional-us-central1"
DEFAULT_DDL_FILE="spanner_ddl.sql"

echo "========================================================"
echo " GCP Spanner Instance & Database Setup "
echo "========================================================"

# 0. Check current GCP project
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ -z "$PROJECT_ID" ]; then
    echo "❌ Error: No Google Cloud project is currently set."
    echo "Please run 'gcloud config set project YOUR_PROJECT_ID' first."
    exit 1
fi
echo "Project: $PROJECT_ID"

echo "Ensuring the Cloud Spanner API is enabled..."
gcloud services enable spanner.googleapis.com --quiet

# ========================================================
# HELPER FUNCTION: Create DB, Check Collisions, Apply DDL
# ========================================================
create_database() {
    local TARGET_INSTANCE=$1
    local DB_NAME=""

    echo ""
    echo "--- Database Setup ---"
    
    # Loop continuously until an available name is provided
    while true; do
        read -p "Enter a name for the new database [default: trial-db]: " DB_INPUT
        DB_NAME=${DB_INPUT:-trial-db}
        
        echo "Checking if '$DB_NAME' is available in instance '$TARGET_INSTANCE'..."
        local DB_EXISTS=$(gcloud spanner databases list \
            --instance="$TARGET_INSTANCE" \
            --filter="name:$DB_NAME" \
            --format="value(name)" 2>/dev/null)
        
        if [ -n "$DB_EXISTS" ]; then
            echo "   -> ⚠️ Collision detected! A database named '$DB_NAME' already exists."
            echo "   -> Please choose a different name."
            echo ""
        else
            echo "   -> ✅ Name available!"
            break # Exit the loop, the name is safe to use
        fi
    done

    echo "   -> 🚀 Creating database: '$DB_NAME'..."
    gcloud spanner databases create "$DB_NAME" \
        --instance="$TARGET_INSTANCE" \
        --database-dialect="GOOGLE_STANDARD_SQL"
    echo "   -> ✅ Database '$DB_NAME' created successfully!"

    # --- DDL LOGIC ---
    echo ""
    read -p "Would you like to apply a DDL schema from a local file to this database? (y/n): " APPLY_DDL
    if [[ "$APPLY_DDL" =~ ^[Yy]$ ]]; then
        while true; do
            read -p "Enter the path to your DDL file [default: $DEFAULT_DDL_FILE]: " DDL_INPUT
            
            # Use the input provided, or fallback to the default constant if empty
            DDL_FILE=${DDL_INPUT:-$DEFAULT_DDL_FILE}
            
            # Check if the file exists and is a regular file
            if [ -f "$DDL_FILE" ]; then
                echo "   -> ⚙️ Applying DDL from '$DDL_FILE'..."
                
                # Apply the DDL to the database
                gcloud spanner databases ddl update "$DB_NAME" \
                    --instance="$TARGET_INSTANCE" \
                    --ddl-file="$DDL_FILE"
                
                echo "   -> ✅ Schema applied successfully!"
                break # Exit the DDL prompt loop
            else
                echo "   -> ❌ Error: File '$DDL_FILE' not found or is not readable."
                echo "   -> Please check the path and try again."
            fi
        done
    fi
}

# ========================================================
# CONDITION 1: Check if a trial instance already exists
# ========================================================
echo "Checking for existing free trial instances in this project..."
EXISTING_FREE_INSTANCE=$(gcloud spanner instances list \
    --filter="instanceType:FREE_INSTANCE" \
    --format="value(name)" 2>/dev/null | head -n 1)

if [ -n "$EXISTING_FREE_INSTANCE" ]; then
    # Extract just the instance ID from the full GCP path
    EXISTING_FREE_INSTANCE=$(basename "$EXISTING_FREE_INSTANCE")
    
    echo ""
    echo "========================================================"
    echo " CONDITION 1: Trial Instance Already Exists"
    echo " Found existing free trial instance: '$EXISTING_FREE_INSTANCE'"
    echo "========================================================"
    
    # Prompt the user to use the existing instance
    read -p "Would you like to use this existing trial instance? (y/n): " USE_EXISTING
    if [[ "$USE_EXISTING" =~ ^[Yy]$ ]]; then
        create_database "$EXISTING_FREE_INSTANCE"
    else
        echo "Exiting without making changes."
    fi
    exit 0
fi

# ========================================================
# CONDITIONS 2 & 3: No Trial Instance Found. Attempt creation.
# ========================================================
echo ""
echo "========================================================"
echo " CONDITION 2: No Trial Instance Found"
echo " Attempting to provision a new free trial instance..."
echo "========================================================"

# Temporarily disable 'set -e' to gracefully catch failure if project is ineligible
set +e
CREATE_OUT=$(gcloud spanner instances create "$INSTANCE_ID" \
    --config="$REGION_CONFIG" \
    --description="Spanner Free Trial" \
    --instance-type="free-instance" 2>&1)
CREATE_STATUS=$?
# Re-enable 'set -e'
set -e

if [ $CREATE_STATUS -eq 0 ]; then
    # Condition 2: Success! The project was eligible.
    echo "✅ Success! Free trial instance '$INSTANCE_ID' created."
    create_database "$INSTANCE_ID"

else
    # Condition 3: Failure (Project ineligible or limits reached)
    echo ""
    echo "========================================================"
    echo " CONDITION 3: Project Not Eligible For Trial"
    echo "========================================================"
    echo "❌ Failed to create a free trial instance. Your project or billing account may not be eligible."
    echo "Error details:"
    echo "> $CREATE_OUT"
    echo "--------------------------------------------------------"
    
    read -p "Would you like to go forward with creating a PAID instance instead? (y/n): " PAID_CHOICE
    if [[ "$PAID_CHOICE" =~ ^[Yy]$ ]]; then
        echo ""
        echo "⚠️ Creating a PAID instance using the absolute lowest cost specifications."
        echo "   (Standard Edition, Regional Config, 100 Processing Units)"
        
        # --- INSTANCE NAME COLLISION LOGIC ---
        PAID_INSTANCE_ID="$INSTANCE_ID"
        while true; do
            read -p "Enter a name for the new paid instance [default: $INSTANCE_ID]: " INST_INPUT
            PAID_INSTANCE_ID=${INST_INPUT:-$INSTANCE_ID}
            
            echo "Checking if instance name '$PAID_INSTANCE_ID' is available..."
            INST_EXISTS=$(gcloud spanner instances list \
                --filter="name:$PAID_INSTANCE_ID" \
                --format="value(name)" 2>/dev/null)
            
            if [ -n "$INST_EXISTS" ]; then
                echo "   -> ⚠️ Collision detected! An instance named '$PAID_INSTANCE_ID' already exists."
                echo "   -> Please choose a different name."
                echo ""
            else
                echo "   -> ✅ Instance name available!"
                break # Exit the loop, the name is safe to use
            fi
        done
        
        echo "   -> 🚀 Creating paid instance: '$PAID_INSTANCE_ID'..."
        gcloud spanner instances create "$PAID_INSTANCE_ID" \
            --config="$REGION_CONFIG" \
            --description="Paid Low-Cost Spanner Instance" \
            --edition="standard" \
            --processing-units=100
        
        echo "   -> ✅ Paid instance '$PAID_INSTANCE_ID' created."
        create_database "$PAID_INSTANCE_ID"
    else
        echo "Exiting without creating resources."
    fi
fi

echo ""
echo "========================================================"
echo " Script complete! "
echo "========================================================"
