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
