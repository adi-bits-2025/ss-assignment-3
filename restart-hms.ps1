# restart-hms.ps1 - Clean restart of HMS on Minikube
# Run from: C:\Users\HP\Documents\WILP\Sem II\ScalableServices\Assignment\ss-assignment-3

$ErrorActionPreference = "Stop"
Write-Host "=== CLEAN RESTART OF HMS ON MINIKUBE ===" -ForegroundColor Cyan

# ------------------------------------------------------------
# 1. Tear down existing Kubernetes resources
# ------------------------------------------------------------
Write-Host "`n[1/9] Deleting namespace hms (if exists)..." -ForegroundColor Yellow
kubectl delete namespace hms --ignore-not-found

# Write-Host "Waiting for namespace termination..."
# $timeout = 60
# $elapsed = 0
# # Check if namespace still exists before waiting
# $ns = kubectl get namespace hms -o name 2>$null
# if ($ns) {
#     while ($elapsed -lt $timeout) {
#         $ns = kubectl get namespace hms -o name 2>$null
#         if (-not $ns) { break }
#         Start-Sleep -Seconds 2
#         $elapsed += 2
#     }
# }

# ------------------------------------------------------------
# 2. Rebuild Docker images inside Minikube's Docker daemon
# ------------------------------------------------------------
Write-Host "`n[2/9] Building Docker images inside Minikube..." -ForegroundColor Yellow
minikube docker-env --shell powershell | Invoke-Expression

$services = @(
    @{Name="patient-service"; Path="./services/patient-service"},
    @{Name="doctor-schedule-service"; Path="./services/doctor-schedule-service"},
    @{Name="appointment-service"; Path="./services/appointment-service"},
    @{Name="prescription-service"; Path="./services/prescription-service"},
    @{Name="billing-service"; Path="./services/billing-service"},
    @{Name="demo-ui"; Path="./services/demo-ui"}
)

foreach ($svc in $services) {
    Write-Host "  Building $($svc.Name)..."
    docker build -t "$($svc.Name):latest" $svc.Path
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Docker build failed for $($svc.Name). Aborting."
        exit 1
    }
}

# minikube docker-env --unset | Invoke-Expression
Write-Host "All images built successfully."

# ------------------------------------------------------------
# 3. Recreate namespace
# ------------------------------------------------------------
Write-Host "`n[3/9] Creating namespace hms..." -ForegroundColor Yellow
kubectl create namespace hms

# ------------------------------------------------------------
# 4. Apply all Kubernetes manifests from infra/k8s
# ------------------------------------------------------------
Write-Host "`n[4/9] Applying Kubernetes manifests..." -ForegroundColor Yellow

$k8sDir = ".\infra\k8s"
if (-not (Test-Path $k8sDir)) {
    Write-Error "Directory $k8sDir not found. Please check your YAML files location."
    exit 1
}
Push-Location $k8sDir

kubectl apply -f hms-storage.yaml -n hms
kubectl apply -f hms-config.yaml -n hms
kubectl apply -f hms-secret.yaml -n hms
kubectl apply -f patient-service.yaml -n hms
kubectl apply -f doctor-schedule-service.yaml -n hms
kubectl apply -f appointment-service.yaml -n hms
kubectl apply -f prescription-service.yaml -n hms
kubectl apply -f billing-service.yaml -n hms
kubectl apply -f prometheus-config.yaml -n hms
kubectl apply -f prometheus-deployment.yaml -n hms
kubectl apply -f grafana-deployment.yaml -n hms
kubectl apply -f demo-ui.yaml -n hms

Pop-Location
Write-Host "Manifests applied."

# # ------------------------------------------------------------
# # 5. Create doctor-service alias (fix for appointment 503)
# # ------------------------------------------------------------
# Write-Host "`n[5/9] Creating doctor-service alias..." -ForegroundColor Yellow
# kubectl expose deployment doctor-schedule-service --name=doctor-service --port=5002 --target-port=5002 -n hms

# ------------------------------------------------------------
# 6. Wait for all pods to be Ready
# ------------------------------------------------------------
Write-Host "`n[6/9] Waiting for all pods to become Ready..." -ForegroundColor Yellow
kubectl wait --for=condition=Ready pods --all -n hms --timeout=120s
Write-Host "All pods are running."

# ------------------------------------------------------------
# 7. Start port-forwarding in background jobs
# ------------------------------------------------------------
Write-Host "`n[7/9] Starting port-forwarding jobs..." -ForegroundColor Yellow
$forwardCmds = @(
    { kubectl port-forward -n hms svc/patient-service 5001:5001 },
    { kubectl port-forward -n hms svc/doctor-schedule-service 5002:5002 },
    { kubectl port-forward -n hms svc/appointment-service 5003:5003 },
    { kubectl port-forward -n hms svc/prescription-service 5004:5004 },
    { kubectl port-forward -n hms svc/billing-service 5005:5005 },
    { kubectl port-forward -n hms svc/prometheus 9090:9090 },
    { kubectl port-forward -n hms svc/grafana 3000:3000 }
)

foreach ($cmd in $forwardCmds) {
    Start-Job -ScriptBlock $cmd | Out-Null
}
Write-Host "Port-forwarding jobs started. Waiting 5 seconds for them to establish..."
Start-Sleep -Seconds 5

# ------------------------------------------------------------
# 8. Run the seed script
# ------------------------------------------------------------
Write-Host "`n[8/9] Running seed script..." -ForegroundColor Yellow
if (Test-Path ".\services\seed_all.py") {
    Push-Location .\services
    python seed_all.py
    Pop-Location
    Write-Host "Seeding complete."
} else {
    Write-Warning "seed_all.py not found in .\services. Skipping seeding."
}

# ------------------------------------------------------------
# 9. Display access URL for Demo UI
# ------------------------------------------------------------
Write-Host "`n[9/9] Retrieving Demo UI URL..." -ForegroundColor Yellow
$url = minikube service demo-ui -n hms --url
Write-Host "================================================" -ForegroundColor Green
Write-Host "HMS is ready! Open the following URL in your browser:" -ForegroundColor Green
Write-Host $url -ForegroundColor White
Write-Host "================================================" -ForegroundColor Green

Write-Host "`nTo stop port-forwarding later, run: Get-Job | Stop-Job; Get-Job | Remove-Job" -ForegroundColor Gray
Write-Host "Script completed successfully." -ForegroundColor Cyan