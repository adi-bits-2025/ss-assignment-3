# HMS Microservices Demo

This repository contains a simple Hospital Management System (HMS) demo built with Python microservices, Docker Compose, and a React-based demo console for project submission walkthroughs.

## What is Included

- 5 backend microservices:
  - Patient Service
  - Doctor Schedule Service
  - Appointment Service
  - Prescription Service
  - Billing Service
- 1 Demo UI:
  - React app that demonstrates service capabilities, validation rules, workflow evidence, and API responses
- Swagger UI enabled for every backend service

## Architecture Summary

The application is implemented as five independently runnable backend services:

- Patient Service manages patient registration and patient profile data.
- Doctor Schedule Service manages doctor details and availability slots.
- Appointment Service manages appointment creation, status updates, and rescheduling.
- Prescription Service manages prescriptions linked to appointments.
- Billing Service manages bills and bill payments.

Each backend service has its own Flask application, Dockerfile, dependency file, SQLite database, API surface, health endpoint, metrics endpoint, and Swagger UI. The services use a database-per-service pattern: each service owns its own database file under its own data volume when run with Docker Compose.

Inter-service communication is synchronous HTTP/REST. Services validate dependent resources through REST calls rather than sharing databases. For example, Appointment Service checks Patient Service and Doctor Schedule Service before booking an appointment, Prescription Service checks Appointment Service before issuing a prescription, and Billing Service checks Patient Service and Appointment Service before creating a bill.

## Requirement Status

This project partially meets the listed microservices requirement.

Met:

- It has at least four microservices. This project has five backend microservices.
- It applies database-per-service. Each service owns its own SQLite database and Docker volume.
- It uses loosely coupled service communication over HTTP/REST APIs instead of direct database access.
- Each service can be built, run, tested, and deployed independently at the container level.


## Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin)
- Port access on:
  - 5001, 5002, 5003, 5004, 5005, 8501

## Quick Start (Recommended)

From repository root:

```bash
docker compose -f infra/docker-compose.yml up --build -d
```

Check running status:

```bash
docker compose -f infra/docker-compose.yml ps
```

## Optional: Seed Dataset

If you want preloaded sample data from CSV files, run the single central seeder:

```bash
cd services
python seed_all.py
```

The seeder reads from `HMS Dataset/` and inserts data through the public REST APIs. Service-local startup seeders were removed to avoid duplicate seed paths and inconsistent behavior.

The central seeder also normalizes known dataset issues:

- It preserves CSV IDs when creating patients, doctors, appointments, prescriptions, bills, and payments so cross-service references stay aligned.
- It makes duplicate seed emails unique before posting them to services with unique email constraints.
- It fixes appointment rows where `slot_end` is not after `slot_start` by using a 30-minute slot.

If you previously seeded with an older script, reset volumes before reseeding:

```bash
docker compose -f infra/docker-compose.yml down -v
docker compose -f infra/docker-compose.yml up --build -d
cd services
python seed_all.py
```

## Optional: Run E2E Workflow Test

From repository root:

```bash
python test/test_workflows.py
```

## Running on Minikube

This repository can also be deployed to a local Kubernetes cluster using Minikube.

### Prerequisites

- `Minikube` installed on Windows (`winget install Kubernetes.minikube`)
- `kubectl` installed and available on PATH
- Docker Desktop or Docker Engine available for the Minikube Docker driver

### Recommended Minikube workflow

1. Clean start Minikube with the Docker driver and preloaded base image:

```powershell
minikube delete --all --purge
docker rm -f minikube 2>$null
docker pull gcr.io/k8s-minikube/kicbase:v0.0.50
minikube start --driver=docker --base-image="gcr.io/k8s-minikube/kicbase:v0.0.50"
```

2. Verify the cluster and node are ready:

```powershell
kubectl cluster-info
kubectl get nodes
```

3. Use Minikube's Docker daemon to build images directly into Minikube:

```powershell
minikube docker-env | Invoke-Expression
# If that does not work, use:
# & minikube -p minikube docker-env --shell powershell | Invoke-Expression
```

4. Build the service images from the project root:

```powershell
docker build -t patient-service:latest ./services/patient-service
docker build -t doctor-schedule-service:latest ./services/doctor-schedule-service
docker build -t appointment-service:latest ./services/appointment-service
docker build -t prescription-service:latest ./services/prescription-service
docker build -t billing-service:latest ./services/billing-service
docker build -t demo-ui:latest ./services/demo-ui
```

5. Ensure all Kubernetes deployments use `imagePullPolicy: Never` so they use the locally built Minikube images.

### Namespace, storage, and config

- Create the `hms` namespace:

```powershell
kubectl create namespace hms
kubectl config set-context --current --namespace=hms
```

- Apply persistent storage, config, and secret manifests from `infra/k8s`:

```powershell
kubectl apply -f infra/k8s/hms-storage.yaml -n hms
kubectl apply -f infra/k8s/hms-config.yaml -n hms
kubectl apply -f infra/k8s/hms-secret.yaml -n hms
```

### Deploy the HMS stack

Apply the service and monitoring manifests in `infra/k8s` to deploy the application.

### Restart script: `restart-hms.ps1`

The `restart-hms.ps1` script automates the full Minikube deployment flow from the repository root.

It performs the following actions:

- deletes the existing `hms` namespace if present
- rebuilds all backend and UI Docker images inside Minikube's Docker daemon
- recreates the `hms` namespace
- applies Kubernetes manifests from `infra/k8s`
- creates an alias service `doctor-service` for `doctor-schedule-service` to avoid appointment service 503 issues
- waits for all pods to become ready
- starts background port-forwarding jobs for the services on ports 5001-5005
- runs `services/seed_all.py` to populate sample data
- prints the Demo UI URL from `minikube service demo-ui -n hms --url`

To stop the port-forwarding jobs later:

```powershell
Get-Job | Stop-Job
Get-Job | Remove-Job
```

## Stop Services

```bash
docker compose -f infra/docker-compose.yml down
```

## Reset Everything (including volumes)

```bash
docker compose -f infra/docker-compose.yml down -v
```

## Troubleshooting

- If a port is already in use, stop the conflicting process/container and rerun Compose.
- If services take time to become healthy, wait 30-60 seconds and refresh the Demo UI.
- If you changed code and need a rebuild:

```bash
docker compose -f infra/docker-compose.yml up --build -d
```
