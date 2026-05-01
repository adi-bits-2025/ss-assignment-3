import os
import time
import uuid
import unittest

import requests


BASE = {
    'patient': os.environ.get('PATIENT_SERVICE_URL', 'http://localhost:5001'),
    'doctor': os.environ.get('DOCTOR_SCHEDULE_SERVICE_URL', 'http://localhost:5002'),
    'appointment': os.environ.get('APPOINTMENT_SERVICE_URL',  'http://localhost:5003',),
    'prescription': os.environ.get('PRESCRIPTION_SERVICE_URL', 'http://localhost:5004',),
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
        for url in BASE.values():
            code, body = _request('GET', f"{url}/health")
            if code != 200 or body.get('status') != 'ok':
                all_up = False
                break
        if all_up:
            return True
        time.sleep(2)
    return False


class HMSE2EWorkflows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not _wait_for_services(timeout=90):
            raise unittest.SkipTest(
                'Services are not healthy within 90 seconds. '
                'Start stack with: cd infra && docker compose up -d'
            )

    def _uid(self):
        return uuid.uuid4().hex[:10]

    def _create_patient(self, uid):
        code, body = _request(
            'POST',
            f"{BASE['patient']}/patients",
            {
                'name': 'Test Patient',
                'email': f'{uid}@test.com',
                'phone': '9000000001',
                'dob': '1990-01-15',
            },
        )
        self.assertEqual(code, 201, body)
        self.assertIn('id', body)
        return body['id']

    def _create_doctor(self, uid):
        code, body = _request(
            'POST',
            f"{BASE['doctor']}/doctors",
            {
                'name': 'Dr. Test',
                'email': f'dr.{uid}@hms.com',
                'phone': '9000000010',
                'department': 'Cardiology',
                'specialization': 'Cardiologist',
            },
        )
        self.assertEqual(code, 201, body)
        self.assertIn('id', body)
        return body['id']

    def _create_appointment(self, patient_id, doctor_id):
        code, body = _request(
            'POST',
            f"{BASE['appointment']}/appointments",
            {
                'patient_id': patient_id,
                'doctor_id': doctor_id,
                'department': 'Cardiology',
                'slot_start': '2026-07-01T10:00:00',
                'slot_end': '2026-07-01T10:30:00',
            },
        )
        self.assertEqual(code, 201, body)
        self.assertEqual(body.get('status'), 'SCHEDULED', body)
        return body['id']

    def test_health_all_services(self):
        for name, url in BASE.items():
            code, body = _request('GET', f"{url}/health")
            self.assertEqual(
                code,
                200,
                msg=f"{name} health endpoint failed: {body}",
            )
            self.assertEqual(body.get('status'), 'ok', body)

    def test_workflow_happy_path(self):
        uid = self._uid()
        patient_id = self._create_patient(uid)
        doctor_id = self._create_doctor(uid)
        appointment_id = self._create_appointment(patient_id, doctor_id)

        code, body = _request(
            'PATCH',
            f"{BASE['appointment']}/appointments/{appointment_id}/reschedule",
            {
                'slot_start': '2026-07-02T09:00:00',
                'slot_end': '2026-07-02T09:30:00',
            },
        )
        self.assertEqual(code, 200, body)
        self.assertTrue(
            body.get('slot_start', '').startswith('2026-07-02'),
            body,
        )

        code, body = _request(
            'PATCH',
            f"{BASE['appointment']}/appointments/{appointment_id}/status",
            {'status': 'COMPLETED'},
        )
        self.assertEqual(code, 200, body)
        self.assertEqual(body.get('status'), 'COMPLETED', body)

        code, body = _request(
            'PATCH',
            f"{BASE['appointment']}/appointments/{appointment_id}/status",
            {'status': 'CANCELLED'},
        )
        self.assertEqual(code, 409, body)

        code, body = _request(
            'POST',
            f"{BASE['prescription']}/prescriptions",
            {
                'appointment_id': appointment_id,
                'patient_id': patient_id,
                'doctor_id': doctor_id,
                'medication': 'Aspirin',
                'dosage': '1-0-1',
                'days': 7,
            },
        )
        self.assertEqual(code, 201, body)
        rx_id = body.get('id')
        self.assertIsNotNone(rx_id, body)

        code, body = _request(
            'GET',
            f"{BASE['prescription']}/prescriptions/{rx_id}",
        )
        self.assertEqual(code, 200, body)
        self.assertEqual(body.get('medication'), 'Aspirin', body)

        code, body = _request(
            'POST',
            f"{BASE['billing']}/bills",
            {
                'patient_id': patient_id,
                'appointment_id': appointment_id,
                'amount': 750,
            },
        )
        self.assertEqual(code, 201, body)
        bill_id = body.get('id')
        self.assertIsNotNone(bill_id, body)
        self.assertEqual(body.get('status'), 'OPEN', body)

        code, body = _request(
            'POST',
            f"{BASE['billing']}/bills/{bill_id}/payments",
            {'amount': 300, 'method': 'CARD'},
        )
        self.assertEqual(code, 201, body)
        self.assertEqual(body.get('bill_status'), 'OPEN', body)

        code, body = _request(
            'POST',
            f"{BASE['billing']}/bills/{bill_id}/payments",
            {'amount': 450, 'method': 'UPI'},
        )
        self.assertEqual(code, 201, body)
        self.assertEqual(body.get('bill_status'), 'PAID', body)

    def test_workflow_validation_path(self):
        uid = self._uid()
        patient_id = self._create_patient(uid)
        doctor_id = self._create_doctor(uid)

        code, body = _request(
            'POST',
            f"{BASE['patient']}/patients",
            {
                'name': 'Dup Patient',
                'email': f'{uid}@test.com',
                'phone': '9000000099',
            },
        )
        self.assertEqual(code, 409, body)

        code, body = _request(
            'POST',
            f"{BASE['appointment']}/appointments",
            {
                'patient_id': 999999,
                'doctor_id': doctor_id,
                'department': 'Cardiology',
                'slot_start': '2026-07-03T11:00:00',
                'slot_end': '2026-07-03T11:30:00',
            },
        )
        self.assertEqual(code, 404, body)

        code, body = _request(
            'POST',
            f"{BASE['appointment']}/appointments",
            {
                'patient_id': patient_id,
                'doctor_id': 999999,
                'department': 'Cardiology',
                'slot_start': '2026-07-03T12:00:00',
                'slot_end': '2026-07-03T12:30:00',
            },
        )
        self.assertEqual(code, 404, body)

        code, body = _request(
            'POST',
            f"{BASE['appointment']}/appointments",
            {'patient_id': patient_id},
        )
        self.assertEqual(code, 400, body)

        code, body = _request(
            'POST',
            f"{BASE['prescription']}/prescriptions",
            {
                'appointment_id': 999999,
                'patient_id': patient_id,
                'doctor_id': doctor_id,
                'medication': 'X',
                'dosage': '1-0-1',
                'days': 1,
            },
        )
        self.assertEqual(code, 404, body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
