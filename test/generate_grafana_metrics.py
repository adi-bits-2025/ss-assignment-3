import os
import sys
import time
import uuid
from datetime import datetime, timedelta

import requests

BASE = {
    'patient': os.environ.get('PATIENT_SERVICE_URL', 'http://localhost:5001'),
    'doctor': os.environ.get('DOCTOR_SCHEDULE_SERVICE_URL', 'http://localhost:5002'),
    'appointment': os.environ.get('APPOINTMENT_SERVICE_URL', 'http://localhost:5003'),
    'prescription': os.environ.get('PRESCRIPTION_SERVICE_URL', 'http://localhost:5004'),
    'billing': os.environ.get('BILLING_SERVICE_URL', 'http://localhost:5005'),
}


def _request(method, url, payload=None, timeout=10):
    try:
        response = requests.request(method, url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        return 503, {'error': str(exc)}

    try:
        body = response.json()
    except ValueError:
        body = {'raw': response.text}
    return response.status_code, body


def _wait_for_services(timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        all_up = True
        for name, base in BASE.items():
            code, body = _request('GET', f'{base}/health')
            if code != 200 or body.get('status') != 'ok':
                all_up = False
                break
        if all_up:
            return True
        time.sleep(2)
    return False


def _uid():
    return uuid.uuid4().hex[:10]


def _create_patient(uid):
    return _request(
        'POST',
        f"{BASE['patient']}/patients",
        {
            'name': f'Test Patient {uid}',
            'email': f'test.patient.{uid}@example.com',
            'phone': f'900{int(uid[:3], 16):07d}'[-10:],
            'dob': '1990-01-15',
        },
    )


def _create_doctor(uid):
    return _request(
        'POST',
        f"{BASE['doctor']}/doctors",
        {
            'name': f'Dr. Metrics {uid}',
            'email': f'dr.metrics.{uid}@hms.test',
            'phone': f'901{int(uid[3:6], 16):07d}'[-10:],
            'department': 'Cardiology',
            'specialization': 'Cardiologist',
        },
    )


def _create_appointment(patient_id, doctor_id, start_dt, end_dt):
    return _request(
        'POST',
        f"{BASE['appointment']}/appointments",
        {
            'patient_id': patient_id,
            'doctor_id': doctor_id,
            'department': 'Cardiology',
            'slot_start': start_dt.isoformat(),
            'slot_end': end_dt.isoformat(),
        },
    )


def _reschedule_appointment(appt_id, start_dt, end_dt):
    return _request(
        'PATCH',
        f"{BASE['appointment']}/appointments/{appt_id}/reschedule",
        {
            'slot_start': start_dt.isoformat(),
            'slot_end': end_dt.isoformat(),
        },
    )


def _update_appointment_status(appt_id, status):
    return _request(
        'PATCH',
        f"{BASE['appointment']}/appointments/{appt_id}/status",
        {'status': status},
    )


def _create_prescription(patient_id, doctor_id, appt_id):
    return _request(
        'POST',
        f"{BASE['prescription']}/prescriptions",
        {
            'appointment_id': appt_id,
            'patient_id': patient_id,
            'doctor_id': doctor_id,
            'medication': 'Aspirin',
            'dosage': '1-0-1',
            'days': 7,
        },
    )


def _create_bill(patient_id, appointment_id, amount):
    return _request(
        'POST',
        f"{BASE['billing']}/bills",
        {
            'patient_id': patient_id,
            'appointment_id': appointment_id,
            'amount': amount,
        },
    )


def _add_payment(bill_id, amount, method):
    return _request(
        'POST',
        f"{BASE['billing']}/bills/{bill_id}/payments",
        {'amount': amount, 'method': method},
    )


def _fetch_url(path):
    return _request('GET', path)


def _print_response(label, code, body):
    print(f'{label}: {code} {body}')
    if code >= 400:
        print('WARNING: encountered an error while generating metrics')


def main():
    print('Starting Grafana metric generator...')
    if not _wait_for_services(timeout=90):
        print('ERROR: One or more services are not healthy. Aborting.')
        sys.exit(1)

    uid = _uid()
    now = datetime.utcnow()
    slot1_start = now + timedelta(days=1, hours=1)
    slot1_end = slot1_start + timedelta(minutes=30)
    slot2_start = slot1_start + timedelta(days=1, hours=1)
    slot2_end = slot2_start + timedelta(minutes=30)

    code, patient_body = _create_patient(uid)
    _print_response('Create patient', code, patient_body)
    if code != 201 or 'id' not in patient_body:
        sys.exit(1)
    patient_id = patient_body['id']

    code, doctor_body = _create_doctor(uid)
    _print_response('Create doctor', code, doctor_body)
    if code != 201 or 'id' not in doctor_body:
        sys.exit(1)
    doctor_id = doctor_body['id']

    code, appt_body = _create_appointment(patient_id, doctor_id, slot1_start, slot1_end)
    _print_response('Create appointment', code, appt_body)
    if code != 201 or 'id' not in appt_body:
        sys.exit(1)
    appointment_id = appt_body['id']

    code, body = _reschedule_appointment(appointment_id, slot2_start, slot2_end)
    _print_response('Reschedule appointment', code, body)

    code, body = _update_appointment_status(appointment_id, 'COMPLETED')
    _print_response('Complete appointment', code, body)

    code, body = _create_prescription(patient_id, doctor_id, appointment_id)
    _print_response('Create prescription', code, body)

    code, bill_body = _create_bill(patient_id, appointment_id, 750)
    _print_response('Create bill', code, bill_body)
    if code != 201 or 'id' not in bill_body:
        sys.exit(1)
    bill_id = bill_body['id']

    code, body = _add_payment(bill_id, 300, 'CARD')
    _print_response('Add partial payment', code, body)

    code, body = _add_payment(bill_id, 450, 'UPI')
    _print_response('Add final payment', code, body)

    # Generate a cancelled appointment and a failed billing event
    code, appt2_body = _create_appointment(patient_id, doctor_id, slot1_start + timedelta(days=3), slot1_end + timedelta(days=3))
    _print_response('Create cancelled appointment', code, appt2_body)
    if code == 201 and 'id' in appt2_body:
        appt2_id = appt2_body['id']
        code, body = _update_appointment_status(appt2_id, 'CANCELLED')
        _print_response('Cancel appointment', code, body)

    code, bill2_body = _create_bill(patient_id, appointment_id, 500)
    _print_response('Create second bill', code, bill2_body)
    if code == 201 and 'id' in bill2_body:
        bill2_id = bill2_body['id']
        code, body = _add_payment(bill2_id, 0, 'CARD')
        _print_response('Attempt failed payment (0 amount)', code, body)

    # Touch some list/read endpoints to increase request counts
    code, body = _fetch_url(f"{BASE['patient']}/patients/{patient_id}")
    _print_response('Read patient', code, body)
    code, body = _fetch_url(f"{BASE['doctor']}/doctors/{doctor_id}")
    _print_response('Read doctor', code, body)
    code, body = _fetch_url(f"{BASE['appointment']}/appointments/{appointment_id}")
    _print_response('Read appointment', code, body)
    code, body = _fetch_url(f"{BASE['billing']}/bills/{bill_id}")
    _print_response('Read bill', code, body)

    print('\nMetrics generation completed.')
    print('Wait a few seconds and refresh Grafana or Prometheus to see the new values.')


if __name__ == '__main__':
    main()
