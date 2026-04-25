# HMS Microservices Demo

This repository contains a simple Hospital Management System (HMS) demo built with Python microservices, Docker Compose, and a Streamlit UI for end-to-end walkthroughs.

## What is Included

- 5 backend microservices:
  - Patient Service
  - Doctor Schedule Service
  - Appointment Service
  - Prescription Service
  - Billing Service
- 1 Demo UI:
  - Streamlit app that drives the full workflow from one screen
- Swagger UI enabled for every backend service

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

If you want preloaded sample data from CSV files:

```bash
cd infra
python seed_all.py
```

## Optional: Run E2E Workflow Test

From repository root:

```bash
python test/test_workflows.py
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
