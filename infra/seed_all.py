"""
seed_all.py — Run this ONCE after docker-compose up to load CSV data into all services.

Usage:
    cd infra/
    python seed_all.py

Reads CSVs from ../doc/HMS Dataset (1)/ and POSTs each row to the service REST APIs.
Skips rows that already exist (409) and prints a summary.
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
    'patient':      'http://localhost:5001',
    'doctor':       'http://localhost:5002',
    'appointment':  'http://localhost:5003',
    'prescription': 'http://localhost:5004',
    'billing':      'http://localhost:5005',
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
            print(f"  ✗ {name}-service did not become healthy. Aborting.")
            sys.exit(1)
    print()


def post(url, payload, label):
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code in (200, 201):
            return True
        if r.status_code == 409:   # already exists — fine
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
    ok = sum(
        post(f"{SERVICES['patient']}/patients",
             {'name': r['name'], 'email': r['email'],
              'phone': r['phone'], 'dob': r.get('dob') or None},
             r['name'])
        for r in rows
    )
    print(f"  Done: {ok}/{len(rows)} patients\n")


def seed_doctors():
    print("=== Seeding Doctors ===")
    rows = read_csv('hms_doctors_indian.csv')
    ok = sum(
        post(f"{SERVICES['doctor']}/doctors",
             {'name': r['name'], 'email': r['email'], 'phone': r['phone'],
              'department': r['department'], 'specialization': r['specialization']},
             r['name'])
        for r in rows
    )
    print(f"  Done: {ok}/{len(rows)} doctors\n")


def seed_appointments():
    print("=== Seeding Appointments ===")
    rows = read_csv('hms_appointments_indian.csv')
    ok = sum(
        post(f"{SERVICES['appointment']}/appointments",
             {'patient_id': int(r['patient_id']), 'doctor_id': int(r['doctor_id']),
              'department': r['department'],
              'slot_start': r['slot_start'], 'slot_end': r['slot_end']},
             f"patient={r['patient_id']}")
        for r in rows
    )
    print(f"  Done: {ok}/{len(rows)} appointments\n")


def seed_prescriptions():
    print("=== Seeding Prescriptions ===")
    rows = read_csv('hms_prescriptions_indian.csv')
    ok = sum(
        post(f"{SERVICES['prescription']}/prescriptions",
             {'appointment_id': int(r['appointment_id']),
              'patient_id': int(r['patient_id']), 'doctor_id': int(r['doctor_id']),
              'medication': r['medication'], 'dosage': r['dosage'], 'days': int(r['days'])},
             f"patient={r['patient_id']}")
        for r in rows
    )
    print(f"  Done: {ok}/{len(rows)} prescriptions\n")


def seed_bills():
    print("=== Seeding Bills ===")
    rows = read_csv('hms_bills_indian.csv')
    ok = sum(
        post(f"{SERVICES['billing']}/bills",
             {'patient_id': int(r['patient_id']),
              'appointment_id': int(r['appointment_id']),
              'amount': float(r['amount'])},
             f"patient={r['patient_id']}")
        for r in rows
    )
    print(f"  Done: {ok}/{len(rows)} bills\n")


def seed_payments():
    print("=== Seeding Payments ===")
    rows = read_csv('hms_payments_indian.csv')

    # Fetch all bills to map CSV bill_id → actual inserted bill_id
    try:
        all_bills = requests.get(f"{SERVICES['billing']}/bills", timeout=10).json()
        bill_id_map = {i + 1: b['id'] for i, b in enumerate(all_bills)}
    except Exception:
        bill_id_map = {}

    ok = 0
    for r in rows:
        actual_bill_id = bill_id_map.get(int(r['bill_id']), int(r['bill_id']))
        if post(f"{SERVICES['billing']}/bills/{actual_bill_id}/payments",
                {'amount': float(r['amount']), 'method': r.get('method', 'CASH').upper()},
                f"bill={r['bill_id']}"):
            ok += 1
    print(f"  Done: {ok}/{len(rows)} payments\n")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    wait_for_services()
    seed_patients()
    seed_doctors()
    seed_appointments()   # depends on patients + doctors existing
    seed_prescriptions()  # depends on appointments existing
    seed_bills()          # depends on patients + appointments existing
    seed_payments()       # depends on bills existing
    print("=== Seeding complete ===")
