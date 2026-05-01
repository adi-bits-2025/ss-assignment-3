# push-services.ps1 - Push individual service code to their respective GitHub repositories
# Run from repository root: .\push-services.ps1

$ErrorActionPreference = "Stop"
Write-Host "=== PUSHING SERVICES TO GITHUB ===" -ForegroundColor Cyan

# Define service-to-repository mappings
$services = @(
    @{
        Name = "Patient Service"
        LocalPath = ".\services\patient-service"
        RepoUrl = "https://github.com/adi-bits-2025/patient-service.git"
    },
    @{
        Name = "Doctor Schedule Service"
        LocalPath = ".\services\doctor-schedule-service"
        RepoUrl = "https://github.com/adi-bits-2025/doctoer-schedule-service.git"
    },
    @{
        Name = "Appointment Service"
        LocalPath = ".\services\appointment-service"
        RepoUrl = "https://github.com/adi-bits-2025/appointment-service.git"
    },
    @{
        Name = "Prescription Service"
        LocalPath = ".\services\prescription-service"
        RepoUrl = "https://github.com/adi-bits-2025/prescription-service.git"
    },
    @{
        Name = "Billing Service"
        LocalPath = ".\services\billing-service"
        RepoUrl = "https://github.com/adi-bits-2025/billing-service.git"
    }
)

$failedServices = @()
$successCount = 0

foreach ($svc in $services) {
    Write-Host "`n[Service] $($svc.Name)" -ForegroundColor Yellow
    
    # Check if service directory exists
    if (-not (Test-Path $svc.LocalPath)) {
        Write-Host "  ERROR: Path not found: $($svc.LocalPath)" -ForegroundColor Red
        $failedServices += $svc.Name
        continue
    }

    Push-Location $svc.LocalPath
    
    try {
        # Check if .git directory exists
        if (-not (Test-Path ".\.git")) {
            Write-Host "  Initializing git repository..." -ForegroundColor Cyan
            git init
            git remote add origin $svc.RepoUrl
        } else {
            Write-Host "  Git repository found. Updating remote..." -ForegroundColor Cyan
            $existingRemote = git remote get-url origin 2>$null
            if ($existingRemote -ne $svc.RepoUrl) {
                Write-Host "  Updating remote URL from: $existingRemote" -ForegroundColor Gray
                git remote remove origin
                git remote add origin $svc.RepoUrl
            }
        }

        # Check if there are changes to commit
        $status = git status --porcelain
        if ([string]::IsNullOrWhiteSpace($status)) {
            Write-Host "  No changes to commit. Skipping." -ForegroundColor Gray
            $successCount++
        } else {
            Write-Host "  Changes detected. Staging and committing..." -ForegroundColor Cyan
            git add -A
            
            $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
            $commitMsg = "Update: $($svc.Name) - $timestamp"
            
            git commit -m $commitMsg
            if ($LASTEXITCODE -ne 0) {
                Write-Host "  ERROR: Failed to commit changes" -ForegroundColor Red
                $failedServices += $svc.Name
            } else {
                Write-Host "  Pushing to GitHub..." -ForegroundColor Cyan
                git push -u origin main 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "  ✓ Successfully pushed $($svc.Name)" -ForegroundColor Green
                    $successCount++
                } else {
                    Write-Host "  ERROR: Failed to push changes" -ForegroundColor Red
                    $failedServices += $svc.Name
                }
            }
        }
    } catch {
        Write-Host "  ERROR: $($_.Exception.Message)" -ForegroundColor Red
        $failedServices += $svc.Name
    } finally {
        Pop-Location
    }
}

# Summary
Write-Host "`n================================================" -ForegroundColor Cyan
Write-Host "Push Summary" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "Successfully pushed: $successCount / $($services.Count)" -ForegroundColor Green

if ($failedServices.Count -gt 0) {
    Write-Host "Failed services:" -ForegroundColor Red
    foreach ($failed in $failedServices) {
        Write-Host "  - $failed" -ForegroundColor Red
    }
    exit 1
} else {
    Write-Host "All services pushed successfully!" -ForegroundColor Green
    exit 0
}
