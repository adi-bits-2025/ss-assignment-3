"""
seed_all.py — Run this ONCE after docker-compose up to load CSV data into all services.

Usage:
    python seed_all.py

Reads CSVs from ../doc/HMS Dataset (1)/ and POSTs each row to the service REST APIs.
Skips rows that fail (e.g. duplicate emails) and prints a summary.
"""

import csv
import os
import sys
import time

import requests

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_DIR  = os.path.join(BASE_DIR, '..', 'doc', 'HMS Dataset (1)')

SERVICES = {
    'patient':     'http://localhost:5001',
    'doctor':      'http://localhost:5002',
    'appointment': 'http://localhost:5003',
    'prescription':'http://localhost:5004',
    'billing':     'http://localhost:5005',
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def wait_for_services(timeout=60):
    print("Waiting for all services to be healthy...")
    deadline = time.time() + timeout
    for name, url in SERVICES.items():
        while time.time() < deadline:
            try:
                r = requests.get(f"{url}/health", timeout=3)
                if r.status_code == 200:
                    print(f"  ✓ {name}-service ready")
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(2)
        else:
            print(f"  ✗ {name}-service did not become healthy in time. Aborting.")
            sys.exit(1)
    print()


def post(url, payload, label):
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code in (200, 201):
            return True
        # 409 = already exists — not an error
        if r.status_code == 409:
            return True
        print(f"    SKIP [{r.status_code}] {label}: {r.text[:120]}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"    ERROR {label}: {e}")
        return False


def read_csv(filename):
    path = os.path.join(CSV_DIR, filename)
    if not os.path.exists(path):
        print(f"  CSV not found: {path}")
        return []
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))

# ── Seeders ───────────────────────────────────────────────────────────────────
def seed_patients():
    print("=== Seeding Patients ===")
    rows = read_csv('hms_patients_indian.csv')
    ok = 0
    for row in rows:
        payload = {
            'name':  row['name'],
            'email': row['email'],
            'phone': row['phone'],
            'dob':   row.get('dob') or None,
        }
        if post(f"{SERVICES['patient']}/patients", payload, row['name']):
            ok += 1
    print(f"  Done: {ok}/{len(rows)} patients inserted\n")


def seed_doctors():
    print("=== Seeding Doctors ===")
    rows = read_csv('hms_doctors_indian.csv')
    ok = 0
    for row in rows:
        payload = {
            'name':           row['name'],
            'email':          row['email'],
            'phone':          row['phone'],
            'department':     row['department'],
            'specialization': row['specialization'],
        }
        if post(f"{SERVICES['doctor']}/doctors", payload, row['name']):
            ok += 1
    print(f"  Done: {ok}/{len(rows)} doctors inserted\n")


def seed_appointments():
    print("=== Seeding Appointments ===")
    rows = read_csv('hms_appointments_indian.csv')
    ok = 0
    for row in rows:
        payload = {
            'patient_id': int(row['patient_id']),
            'doctor_id':  int(row['doctor_id']),
            'department': row['department'],
            'slot_start': row['slot_start'],
            'slot_end':   row['slot_end'],
        }
        if post(f"{SERVICES['appointment']}/appointments", payload,
                f"appt patient={row['patient_id']}"):
            ok += 1
    print(f"  Done: {ok}/{len(rows)} appointments inserted\n")


def seed_prescriptions():
    print("=== Seeding Prescriptions ===")
    rows = read_csv('hms_prescriptions_indian.csv')
    ok = 0
    for row in rows:
        payload = {
            'appointment_id': int(row['appointment_id']),
            'patient_id':     int(row['patient_id']),
            'doctor_id':      int(row['doctor_id']),
            'medication':     row['medication'],
            'dosage':         row['dosage'],
            'days':           int(row['days']),
        }
        if post(f"{SERVICES['prescription']}/prescriptions", payload,
                f"rx patient={row['patient_id']}"):
            ok += 1
    print(f"  Done: {ok}/{len(rows)} prescriptions inserted\n")


def seed_bills():
    print("=== Seeding Bills ===")
    rows = read_csv('hms_bills_indian.csv')
    ok = 0
    for row in rows:
        payload = {
            'patient_id':     int(row['patient_id']),
            'appointment_id': int(row['appointment_id']),
            'amount':         float(row['amount']),
        }
        if post(f"{SERVICES['billing']}/bills", payload,
                f"bill patient={row['patient_id']}"):
            ok += 1
    print(f"  Done: {ok}/{len(rows)} bills inserted\n")


def seed_payments():
    print("=== Seeding Payments ===")
    rows = read_csv('hms_payments_indian.csv')
    ok = 0

    # Build bill_id → internal bill_id map by fetching all bills
    try:
        all_bills = requests.get(f"{SERVICES['billing']}/bills", timeout=10).json()
        # Map appointment_id-based lookup isn't available, so we use bill list order
        # We index by position: CSV bill_id maps to the nth bill created
        bill_id_map = {i + 1: b['id'] for i, b in enumerate(all_bills)}
    except Exception:
        bill_id_map = {}

    for row in rows:
        csv_bill_id = int(row['bill_id'])
        actual_bill_id = bill_id_map.get(csv_bill_id, csv_bill_id)
        payload = {
            'amount': float(row['amount']),
            'method': row.get('method', 'CASH').upper(),
        }
        if post(f"{SERVICES['billing']}/bills/{actual_bill_id}/payments", payload,
                f"payment bill={csv_bill_id}"):
            ok += 1
    print(f"  Done: {ok}/{len(rows)} payments inserted\n")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    wait_for_services()
    seed_patients()
    seed_doctors()
    # Appointments cross-validate patient + doctor — seed those first
    seed_appointments()
    seed_prescriptions()
    seed_bills()
    seed_payments()
    print("=== Seeding complete ===")
