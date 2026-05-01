# Demo UI

React-based project submission console for the HMS microservices demo.

The UI is designed for a formal demo rather than daily hospital operations. It has separate tabs for patient, doctor scheduling, appointment, billing, prescription, payment, notification, and API details. Each tab includes actions, outputs, and rule-validation messages.

## Run With Docker Compose

From repository root:

```bash
docker compose -f infra/docker-compose.yml up --build -d
```

Open:

```text
http://localhost:8501
```

## Run Locally

```bash
cd services/demo-ui
npm install
npm run build
npm start
```

The local server uses port `8501` by default. To use another port:

```bash
$env:PORT="8502"
npm start
```

## Service Environment Variables

- `PATIENT_SERVICE_URL` defaults to `http://localhost:5001`
- `DOCTOR_SERVICE_URL` defaults to `http://localhost:5002`
- `APPOINTMENT_SERVICE_URL` defaults to `http://localhost:5003`
- `PRESCRIPTION_SERVICE_URL` defaults to `http://localhost:5004`
- `BILLING_SERVICE_URL` defaults to `http://localhost:5005`

When running through Docker Compose, these are set to the internal service hostnames.

## Demo Coverage

- Patient CRUD, search by name or phone, and PII masking output.
- Doctor listings, department filtering, and slot validation.
- Appointment booking, rescheduling, cancellation, completion, and conflict scenario output.
- Billing generation, tax calculation, cancellation adjustment, and bill status handling.
- Prescription creation, retrieval, and invalid appointment rejection.
- Payment idempotency scenario and notification alert display.
- API details for `/v1` demo paths, OpenAPI links, standard error shape, pagination, filtering, and database-per-service ownership.
