#!/bin/bash
# push-services.sh - Push individual service code to their respective GitHub repositories
# Run from repository root: ./push-services.sh

set -e

echo "=== PUSHING SERVICES TO GITHUB ==="

# Define service-to-repository mappings
declare -A services=(
    [patient-service]="https://github.com/adi-bits-2025/patient-service.git"
    [doctor-schedule-service]="https://github.com/adi-bits-2025/doctoer-schedule-service.git"
    [appointment-service]="https://github.com/adi-bits-2025/appointment-service.git"
    [prescription-service]="https://github.com/adi-bits-2025/prescription-service.git"
    [billing-service]="https://github.com/adi-bits-2025/billing-service.git"
)

failed_services=()
success_count=0

for service_name in "${!services[@]}"; do
    repo_url="${services[$service_name]}"
    local_path="./services/$service_name"
    
    echo ""
    echo "[Service] $service_name"
    
    # Check if service directory exists
    if [ ! -d "$local_path" ]; then
        echo "  ERROR: Path not found: $local_path"
        failed_services+=("$service_name")
        continue
    fi
    
    cd "$local_path"
    
    # Check if .git directory exists
    if [ ! -d ".git" ]; then
        echo "  Initializing git repository..."
        git init
        git remote add origin "$repo_url"
    else
        echo "  Git repository found. Updating remote..."
        existing_remote=$(git remote get-url origin 2>/dev/null || echo "")
        if [ "$existing_remote" != "$repo_url" ]; then
            echo "  Updating remote URL from: $existing_remote"
            git remote remove origin
            git remote add origin "$repo_url"
        fi
    fi
    
    # Check if there are changes to commit
    if git diff-index --quiet HEAD -- 2>/dev/null; then
        # No changes
        echo "  No changes to commit. Skipping."
        ((success_count++))
    else
        echo "  Changes detected. Staging and committing..."
        git add -A
        
        timestamp=$(date "+%Y-%m-%d %H:%M:%S")
        commit_msg="Update: $service_name - $timestamp"
        
        if git commit -m "$commit_msg"; then
            echo "  Pushing to GitHub..."
            if git push -u origin main 2>&1; then
                echo "  ✓ Successfully pushed $service_name"
                ((success_count++))
            else
                echo "  ERROR: Failed to push changes"
                failed_services+=("$service_name")
            fi
        else
            echo "  ERROR: Failed to commit changes"
            failed_services+=("$service_name")
        fi
    fi
    
    cd - > /dev/null
done

# Summary
echo ""
echo "================================================"
echo "Push Summary"
echo "================================================"
echo "Successfully pushed: $success_count / ${#services[@]}"

if [ ${#failed_services[@]} -gt 0 ]; then
    echo "Failed services:"
    for failed in "${failed_services[@]}"; do
        echo "  - $failed"
    done
    exit 1
else
    echo "All services pushed successfully!"
    exit 0
fi
