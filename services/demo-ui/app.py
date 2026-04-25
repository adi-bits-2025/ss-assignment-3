import os
from datetime import datetime, timedelta
from uuid import uuid4

import requests
import streamlit as st

st.set_page_config(page_title='HMS Workflow Demo', page_icon='🏥', layout='wide')

DEFAULT_BASE_URLS = {
    'patient': os.environ.get('PATIENT_SERVICE_URL', 'http://localhost:5001'),
    'doctor': os.environ.get('DOCTOR_SERVICE_URL', 'http://localhost:5002'),
    'appointment': os.environ.get('APPOINTMENT_SERVICE_URL', 'http://localhost:5003'),
    'prescription': os.environ.get('PRESCRIPTION_SERVICE_URL', 'http://localhost:5004'),
    'billing': os.environ.get('BILLING_SERVICE_URL', 'http://localhost:5005'),
}


def init_state():
    defaults = {
        'uid': uuid4().hex[:8],
        'patient_id': None,
        'doctor_id': None,
        'appointment_id': None,
        'prescription_id': None,
        'bill_id': None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


init_state()


st.title('Hospital Microservices Demo Console')
st.caption('Simple UI for a 15-minute end-to-end workflow recording')

with st.sidebar:
    st.subheader('Service URLs')
    for service, base_url in DEFAULT_BASE_URLS.items():
        st.session_state[f'{service}_url'] = st.text_input(
            f'{service.title()} Service',
            value=st.session_state.get(f'{service}_url', base_url),
        ).rstrip('/')

    if st.button('Generate New Test User IDs'):
        st.session_state['uid'] = uuid4().hex[:8]
        st.session_state['patient_id'] = None
        st.session_state['doctor_id'] = None
        st.session_state['appointment_id'] = None
        st.session_state['prescription_id'] = None
        st.session_state['bill_id'] = None
        st.success('Reset workflow state for a fresh demo run.')

    st.markdown('### Swagger Links')
    for service in DEFAULT_BASE_URLS:
        base = st.session_state.get(f'{service}_url', DEFAULT_BASE_URLS[service]).rstrip('/')
        st.markdown(f'- [{service.title()} Swagger]({base}/swagger)')


def service_base(name):
    return st.session_state[f'{name}_url'].rstrip('/')


def call_api(method, service, path, payload=None):
    url = f"{service_base(service)}{path}"
    try:
        response = requests.request(method, url, json=payload, timeout=10)
        body = response.json() if response.content else {}
    except ValueError:
        body = {'raw': response.text}
    except requests.RequestException as exc:
        return False, {'error': str(exc)}, None, url

    ok = response.status_code < 400
    return ok, body, response.status_code, url


def render_response(title, result):
    ok, body, status, url = result
    if status is None:
        st.error(f'{title} failed: {body.get("error")}')
        return

    if ok:
        st.success(f'{title} succeeded ({status})')
    else:
        st.error(f'{title} failed ({status})')
    st.write(f'URL: {url}')
    st.json(body)


col1, col2, col3, col4, col5 = st.columns(5)
for idx, service in enumerate(['patient', 'doctor', 'appointment', 'prescription', 'billing']):
    with [col1, col2, col3, col4, col5][idx]:
        ok, body, status, _ = call_api('GET', service, '/health')
        if ok and body.get('status') == 'ok':
            st.metric(service.title(), 'Healthy')
        else:
            st.metric(service.title(), f'Unhealthy ({status})')

st.divider()

workflow = st.tabs([
    '1) Register Patient',
    '2) Register Doctor',
    '3) Book & Complete Appointment',
    '4) Issue Prescription',
    '5) Billing & Payment',
    '6) Negative Test',
])

with workflow[0]:
    uid = st.session_state['uid']
    default_email = f'{uid}@demo.com'
    with st.form('patient_form'):
        name = st.text_input('Patient Name', 'Demo Patient')
        email = st.text_input('Patient Email', default_email)
        phone = st.text_input('Phone', '9000001001')
        dob = st.date_input('DOB', datetime(1995, 1, 15))
        submit = st.form_submit_button('Create Patient')

    if submit:
        payload = {
            'name': name,
            'email': email,
            'phone': phone,
            'dob': dob.isoformat(),
        }
        result = call_api('POST', 'patient', '/patients', payload)
        render_response('Create patient', result)
        ok, body, _, _ = result
        if ok:
            st.session_state['patient_id'] = body.get('id')

    st.info(f"Current patient_id: {st.session_state.get('patient_id')}")

with workflow[1]:
    uid = st.session_state['uid']
    with st.form('doctor_form'):
        name = st.text_input('Doctor Name', 'Dr. Demo')
        email = st.text_input('Doctor Email', f'dr.{uid}@demo.com')
        phone = st.text_input('Doctor Phone', '9000002001')
        department = st.text_input('Department', 'Cardiology')
        specialization = st.text_input('Specialization', 'Cardiologist')
        submit = st.form_submit_button('Create Doctor')

    if submit:
        payload = {
            'name': name,
            'email': email,
            'phone': phone,
            'department': department,
            'specialization': specialization,
        }
        result = call_api('POST', 'doctor', '/doctors', payload)
        render_response('Create doctor', result)
        ok, body, _, _ = result
        if ok:
            st.session_state['doctor_id'] = body.get('id')

    st.info(f"Current doctor_id: {st.session_state.get('doctor_id')}")

with workflow[2]:
    patient_id = st.session_state.get('patient_id')
    doctor_id = st.session_state.get('doctor_id')
    st.write(f'Using patient_id={patient_id}, doctor_id={doctor_id}')

    now = datetime.now().replace(second=0, microsecond=0) + timedelta(days=1)
    default_start = now.isoformat(timespec='minutes')
    default_end = (now + timedelta(minutes=30)).isoformat(timespec='minutes')
    slot_start = st.text_input('Slot Start (ISO 8601)', default_start)
    slot_end = st.text_input('Slot End (ISO 8601)', default_end)

    if st.button('Book Appointment', disabled=not (patient_id and doctor_id)):
        payload = {
            'patient_id': patient_id,
            'doctor_id': doctor_id,
            'department': 'Cardiology',
            'slot_start': slot_start,
            'slot_end': slot_end,
        }
        result = call_api('POST', 'appointment', '/appointments', payload)
        render_response('Book appointment', result)
        ok, body, _, _ = result
        if ok:
            st.session_state['appointment_id'] = body.get('id')

    appt_id = st.session_state.get('appointment_id')
    st.info(f'Current appointment_id: {appt_id}')

    if st.button('Mark Appointment Completed', disabled=not appt_id):
        result = call_api(
            'PATCH',
            'appointment',
            f'/appointments/{appt_id}/status',
            {'status': 'COMPLETED'},
        )
        render_response('Update appointment status', result)

with workflow[3]:
    patient_id = st.session_state.get('patient_id')
    doctor_id = st.session_state.get('doctor_id')
    appt_id = st.session_state.get('appointment_id')
    st.write(f'Using patient_id={patient_id}, doctor_id={doctor_id}, appointment_id={appt_id}')

    with st.form('rx_form'):
        medication = st.text_input('Medication', 'Aspirin')
        dosage = st.text_input('Dosage', '1-0-1')
        days = st.number_input('Days', min_value=1, max_value=60, value=7)
        submit = st.form_submit_button('Issue Prescription')

    if submit:
        payload = {
            'appointment_id': appt_id,
            'patient_id': patient_id,
            'doctor_id': doctor_id,
            'medication': medication,
            'dosage': dosage,
            'days': int(days),
        }
        result = call_api('POST', 'prescription', '/prescriptions', payload)
        render_response('Create prescription', result)
        ok, body, _, _ = result
        if ok:
            st.session_state['prescription_id'] = body.get('id')

    st.info(f"Current prescription_id: {st.session_state.get('prescription_id')}")

with workflow[4]:
    patient_id = st.session_state.get('patient_id')
    appt_id = st.session_state.get('appointment_id')
    st.write(f'Using patient_id={patient_id}, appointment_id={appt_id}')

    amount = st.number_input('Bill Amount', min_value=100, value=750, step=50)

    if st.button('Create Bill', disabled=not (patient_id and appt_id)):
        payload = {
            'patient_id': patient_id,
            'appointment_id': appt_id,
            'amount': float(amount),
        }
        result = call_api('POST', 'billing', '/bills', payload)
        render_response('Create bill', result)
        ok, body, _, _ = result
        if ok:
            st.session_state['bill_id'] = body.get('id')

    bill_id = st.session_state.get('bill_id')
    st.info(f'Current bill_id: {bill_id}')

    pay1, pay2 = st.columns(2)
    with pay1:
        if st.button('Pay 300 (CARD)', disabled=not bill_id):
            result = call_api(
                'POST',
                'billing',
                f'/bills/{bill_id}/payments',
                {'amount': 300, 'method': 'CARD'},
            )
            render_response('Partial payment', result)

    with pay2:
        if st.button('Pay Remaining 450 (UPI)', disabled=not bill_id):
            result = call_api(
                'POST',
                'billing',
                f'/bills/{bill_id}/payments',
                {'amount': 450, 'method': 'UPI'},
            )
            render_response('Final payment', result)

with workflow[5]:
    appt_id = st.session_state.get('appointment_id')
    st.write('This demonstrates one expected conflict response for your viva/demo.')

    if st.button('Try Cancelling Completed Appointment', disabled=not appt_id):
        result = call_api(
            'PATCH',
            'appointment',
            f'/appointments/{appt_id}/status',
            {'status': 'CANCELLED'},
        )
        render_response('Negative test: cancel completed appointment', result)

st.divider()
st.write('Demo tip: Keep this app open and show Swagger in separate tabs from sidebar links.')
