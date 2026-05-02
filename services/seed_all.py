"""
Seed all HMS services from the CSV files.

Usage:
    cd services
    python seed_all.py
"""

import csv
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', 'HMS Dataset'))

SERVICES = {
    'patient': 'http://localhost:5001',
    'doctor-schedule': 'http://localhost:5002',
    'appointment': 'http://localhost:5003',
    'prescription': 'http://localhost:5004',
    'billing': 'http://localhost:5005',
}


def wait_for_services(timeout=60):
    print("Waiting for all services to be healthy...")
    for name, url in SERVICES.items():
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                response = requests.get(f"{url}/health", timeout=3)
                if response.status_code == 200:
                    print(f"  OK {name}-service ready")
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(2)
        else:
            print(f"  FAIL {name}-service did not become healthy in time. Aborting.")
            sys.exit(1)
    print()


def post(url, payload, label):
    try:
        response = requests.post(url, json=payload, timeout=10)
    except requests.exceptions.RequestException as exc:
        print(f"    ERROR {label}: {exc}")
        return False

    if response.status_code in (200, 201, 409):
        return True

    print(f"    SKIP [{response.status_code}] {label}: {response.text[:160]}")
    return False


def patch(url, payload, label):
    try:
        response = requests.patch(url, json=payload, timeout=10)
    except requests.exceptions.RequestException as exc:
        print(f"    ERROR {label}: {exc}")
        return False

    if response.status_code == 405:
        # Some clients, proxies, or environments may not allow PATCH on this endpoint.
        # Fall back to POST for compatibility with the appointment service status endpoint.
        try:
            response = requests.post(url, json=payload, timeout=10)
        except requests.exceptions.RequestException as exc:
            print(f"    ERROR {label} fallback POST: {exc}")
            return False

    if response.status_code in (200, 201, 409):
        return True

    print(f"    SKIP [{response.status_code}] {label}: {response.text[:160]}")
    return False


def read_csv(filename):
    path = os.path.join(CSV_DIR, filename)
    if not os.path.exists(path):
        print(f"  CSV not found: {path}")
        return []
    with open(path, newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def unique_email(row, email_counts, id_field):
    email = row['email']
    if email_counts[email] == 1:
        return email

    local, domain = email.split('@', 1)
    return f"{local}+{row[id_field]}@{domain}"


def fixed_slot(index):
    # Start tomorrow at 10:00:00 UTC
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    
    slots_per_day = 18 # 10:00 to 19:00 is 9 hours, so 18 slots of 30 mins
    
    days_to_add = index // slots_per_day
    slots_to_add = index % slots_per_day
    
    slot_start = tomorrow + timedelta(days=days_to_add, minutes=slots_to_add * 30)
    slot_end = slot_start + timedelta(minutes=30)
    
    return slot_start.isoformat(), slot_end.isoformat()


def seed_patients():
    print("=== Seeding Patients ===")
    rows = read_csv('hms_patients_indian.csv')
    email_counts = Counter(row['email'] for row in rows)
    ok = 0

    for row in rows:
        payload = {
            'id': int(row['patient_id']),
            'name': row['name'],
            'email': unique_email(row, email_counts, 'patient_id'),
            'phone': row['phone'],
            'dob': row.get('dob') or None,
        }
        if post(f"{SERVICES['patient']}/patients", payload, f"patient={row['patient_id']}"):
            ok += 1

    print(f"  Done: {ok}/{len(rows)} patients\n")


def seed_doctors():
    print("=== Seeding Doctors ===")
    rows = read_csv('hms_doctors_indian.csv')
    email_counts = Counter(row['email'] for row in rows)
    ok = 0

    for row in rows:
        payload = {
            'id': int(row['doctor_id']),
            'name': row['name'],
            'email': unique_email(row, email_counts, 'doctor_id'),
            'phone': row['phone'],
            'department': row['department'],
            'specialization': row['specialization'],
        }
        if post(f"{SERVICES['doctor-schedule']}/doctors", payload, f"doctor={row['doctor_id']}"):
            ok += 1

    print(f"  Done: {ok}/{len(rows)} doctors\n")


def seed_appointments():
    print("=== Seeding Appointments ===")
    rows = read_csv('hms_appointments_indian.csv')
    ok = 0
    fixed = 0
    
    doctors = read_csv('hms_doctors_indian.csv')
    doc_depts = {row['doctor_id']: row['department'] for row in doctors}

    for i, row in enumerate(rows):
        slot_start, slot_end = fixed_slot(i)
        fixed += 1
        # First, publish this slot for the doctor so the appointment service accepts it
        slot_payload = {
            'slot_start': slot_start,
            'slot_end': slot_end
        }
        post(f"{SERVICES['doctor-schedule']}/doctors/{row['doctor_id']}/slots", slot_payload, f"doc_slot={row['doctor_id']}")

        payload = {
            'id': int(row['appointment_id']),
            'patient_id': int(row['patient_id']),
            'doctor_id': int(row['doctor_id']),
            'department': doc_depts.get(row['doctor_id'], row['department']),
            'slot_start': slot_start,
            'slot_end': slot_end,
        }
        if post(
            f"{SERVICES['appointment']}/appointments",
            payload,
            f"appt={row['appointment_id']} patient={row['patient_id']}",
        ):
            ok += 1
            # Update status using generic PATCH to avoid triggering auto-billing
            target_status = row.get('status', 'SCHEDULED').upper()
            if target_status != 'SCHEDULED':
                patch(
                    f"{SERVICES['appointment']}/appointments/{row['appointment_id']}/status",
                    {'status': target_status},
                    f"appt_status={row['appointment_id']} to {target_status}"
                )

    print(f"  Done: {ok}/{len(rows)} appointments ({fixed} slot_end values fixed)\n")


def seed_prescriptions():
    print("=== Seeding Prescriptions ===")
    rows = read_csv('hms_prescriptions_indian.csv')
    ok = 0

    for row in rows:
        payload = {
            'id': int(row['prescription_id']),
            'appointment_id': int(row['appointment_id']),
            'patient_id': int(row['patient_id']),
            'doctor_id': int(row['doctor_id']),
            'medication': row['medication'],
            'dosage': row['dosage'],
            'days': int(row['days']),
        }
        if post(f"{SERVICES['prescription']}/prescriptions", payload, f"rx={row['prescription_id']}"):
            ok += 1

    print(f"  Done: {ok}/{len(rows)} prescriptions\n")


def seed_bills():
    print("=== Seeding Bills ===")
    rows = read_csv('hms_bills_indian.csv')
    ok = 0

    for row in rows:
        payload = {
            'id': int(row['bill_id']),
            'patient_id': int(row['patient_id']),
            'appointment_id': int(row['appointment_id']),
            'amount': float(row['amount']),
            'status': 'OPEN',
        }
        if post(f"{SERVICES['billing']}/bills", payload, f"bill={row['bill_id']} patient={row['patient_id']}"):
            ok += 1

    print(f"  Done: {ok}/{len(rows)} bills\n")


def seed_payments():
    print("=== Seeding Payments ===")
    rows = read_csv('hms_payments_indian.csv')
    ok = 0

    for row in rows:
        payload = {
            'id': int(row['payment_id']),
            'amount': float(row['amount']),
            'method': row.get('method', 'CASH').upper(),
            'idempotency_key': f"seed-pay-{row['payment_id']}"
        }
        if post(f"{SERVICES['billing']}/bills/{int(row['bill_id'])}/payments", payload, f"payment={row['payment_id']}"):
            ok += 1

    print(f"  Done: {ok}/{len(rows)} payments\n")


if __name__ == '__main__':
    wait_for_services()
    seed_patients()
    seed_doctors()
    seed_appointments()
    seed_prescriptions()
    seed_bills()
    seed_payments()
    print("=== Seeding complete ===")
