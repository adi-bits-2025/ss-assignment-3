# Demo UI

Simple Streamlit UI for recording an end-to-end HMS microservices flow.

## Run locally

```bash
cd services/demo-ui
pip install -r requirements.txt
streamlit run app.py
```

UI will start at: `http://localhost:8501`

## Optional environment variables

- `PATIENT_SERVICE_URL` (default: `http://localhost:5001`)
- `DOCTOR_SERVICE_URL` (default: `http://localhost:5002`)
- `APPOINTMENT_SERVICE_URL` (default: `http://localhost:5003`)
- `PRESCRIPTION_SERVICE_URL` (default: `http://localhost:5004`)
- `BILLING_SERVICE_URL` (default: `http://localhost:5005`)

## Swagger links

From the app sidebar, open each service Swagger at:

- `/swagger`
- raw OpenAPI json at `/swagger.json`
