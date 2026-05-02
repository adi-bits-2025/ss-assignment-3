import os
import time
import logging
from datetime import datetime, timedelta, time as dt_time

import requests
from flask import Flask, request, jsonify, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

from models import db, Appointment, VALID_STATUSES, ALLOWED_TRANSITIONS

# ── App & DB ──────────────────────────────────────────────────────────────────
app = Flask(__name__)

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), 'data'))
os.makedirs(DATA_DIR, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(DATA_DIR, 'appointments.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {'check_same_thread': False, 'timeout': 30}
}
db.init_app(app)

with app.app_context():
    @event.listens_for(db.engine, 'connect')
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA busy_timeout=30000')
        cursor.close()

# ── Service URLs ──────────────────────────────────────────────────────────────
PATIENT_SERVICE_URL          = os.environ.get('PATIENT_SERVICE_URL',          'http://localhost:5001')
DOCTOR_SCHEDULE_SERVICE_URL  = os.environ.get('DOCTOR_SCHEDULE_SERVICE_URL',  'http://localhost:5002')
BILLING_SERVICE_URL          = os.environ.get('BILLING_SERVICE_URL',          'http://localhost:5005')

# ── Business constants ────────────────────────────────────────────────────────
CLINIC_OPEN            = dt_time(10, 0)   # 10:00 AM
CLINIC_CLOSE           = dt_time(19, 0)   # 07:00 PM
SLOT_DURATION_MINUTES  = 30
LEAD_TIME_BOOK_HOURS   = 2    # Minimum hours before slot to book
LEAD_TIME_CANCEL_HOURS = 2    # Cancellation > 2h → full refund; ≤ 2h → 50% charge
LEAD_TIME_RESCHEDULE_H = 1    # Rescheduling not allowed within 1 h of current slot
MAX_RESCHEDULES        = 2
NO_SHOW_GRACE_MINUTES  = 15   # Reception marks NO_SHOW after 15 minutes

# ── JSON Logging ──────────────────────────────────────────────────────────────
logger = logging.getLogger('appointment-service')
logger.setLevel(logging.INFO)
_h = logging.StreamHandler()
_h.setFormatter(jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s'))
logger.addHandler(_h)
logger.propagate = False

# ── Prometheus ────────────────────────────────────────────────────────────────
REQUEST_COUNT        = Counter('http_requests_total', 'Total HTTP requests',
                                ['service', 'method', 'endpoint', 'status'])
APPOINTMENTS_CREATED  = Counter('appointments_created_total', 'Total appointments booked')
APPOINTMENTS_CANCELLED = Counter('appointments_cancelled_total', 'Total appointments cancelled')


@app.before_request
def _start_timer():
    g.t0 = time.time()


@app.after_request
def _log_request(resp):
    dur = round((time.time() - g.t0) * 1000, 2)
    REQUEST_COUNT.labels('appointment-service', request.method,
                         request.endpoint or request.path, resp.status_code).inc()
    logger.info('request', extra={
        'method': request.method, 'path': request.path,
        'status': resp.status_code, 'duration_ms': dur,
    })
    return resp


@app.route('/metrics')
def metrics():
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'appointment-service'})


SWAGGER_UI_HTML = """
<!doctype html><html><head><meta charset=\"utf-8\"/>
<title>Appointment Service API Docs</title>
<link rel=\"stylesheet\" href=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui.css\"/>
</head><body><div id=\"swagger-ui\"></div>
<script src=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js\"></script>
<script>window.onload=function(){SwaggerUIBundle({url:'/swagger.json',dom_id:'#swagger-ui'});}</script>
</body></html>"""


@app.route('/swagger')
def swagger_ui():
    return SWAGGER_UI_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route('/swagger.json')
def swagger_json():
    return jsonify({
        'openapi': '3.0.3',
        'info': {'title': 'Appointment Service API', 'version': '1.0.0'},
        'servers': [{'url': request.host_url.rstrip('/')}],
        'paths': {
            '/appointments': {
                'get':  {'summary': 'List appointments'},
                'post': {'summary': 'Book appointment'}
            },
            '/appointments/{id}': {
                'get': {'summary': 'Get appointment'}
            },
            '/appointments/{id}/reschedule': {
                'patch': {'summary': 'Reschedule (max 2, ≥1h before current slot)'}
            },
            '/appointments/{id}/cancel': {
                'post': {'summary': 'Cancel appointment (cancellation policy applied)'}
            },
            '/appointments/{id}/complete': {
                'post': {'summary': 'Mark appointment COMPLETED, trigger billing'}
            },
            '/appointments/{id}/noshow': {
                'post': {'summary': 'Mark NO_SHOW after grace period, trigger billing'}
            },
            '/appointments/{id}/status': {
                'patch': {'summary': 'Generic status update (state-machine enforced)'}
            },
        }
    })


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verify_patient(patient_id):
    """Returns (ok, error_msg, patient_data). Checks existence AND is_active."""
    try:
        resp = requests.get(f"{PATIENT_SERVICE_URL}/patients/{patient_id}", timeout=5)
        if resp.status_code == 404:
            return False, f"Patient {patient_id} not found", None
        resp.raise_for_status()
        data = resp.json()
        if not data.get('is_active', True):
            return False, f"Patient {patient_id} is inactive and cannot book appointments", None
        return True, None, data
    except requests.exceptions.ConnectionError:
        return False, "Patient service unavailable", None
    except requests.exceptions.Timeout:
        return False, "Patient service timed out", None


def _verify_doctor(doctor_id, department=None):
    """Returns (ok, error_msg, doctor_data). Checks existence, is_active, and optional department."""
    try:
        resp = requests.get(f"{DOCTOR_SCHEDULE_SERVICE_URL}/doctors/{doctor_id}", timeout=5)
        if resp.status_code == 404:
            return False, f"Doctor {doctor_id} not found", None
        resp.raise_for_status()
        data = resp.json()
        if not data.get('is_active', True):
            return False, f"Doctor {doctor_id} is inactive and cannot accept appointments", None
        if department:
            doc_dept = (data.get('department') or '').strip().lower()
            req_dept  = department.strip().lower()
            if doc_dept != req_dept:
                return False, (
                    f"Department mismatch: doctor belongs to '{data.get('department')}', "
                    f"requested '{department}'"
                ), None
        return True, None, data
    except requests.exceptions.ConnectionError:
        return False, "Doctor service unavailable", None
    except requests.exceptions.Timeout:
        return False, "Doctor service timed out", None


def _verify_doctor_published_slot(doctor_id, slot_start, slot_end):
    """Ensure the doctor has a published slot in doctor-schedule-service that covers this time."""
    try:
        resp = requests.get(f"{DOCTOR_SCHEDULE_SERVICE_URL}/doctors/{doctor_id}/slots?available=true", timeout=5)
        if resp.status_code != 200:
            return "Could not fetch doctor availability slots"
        slots = resp.json()
        for s in slots:
            pub_start = datetime.fromisoformat(s['slot_start'])
            pub_end   = datetime.fromisoformat(s['slot_end'])
            # The requested slot must be completely encompassed by a published available slot.
            if slot_start >= pub_start and slot_end <= pub_end:
                return None
        return "Doctor is not available during the requested time slot. Please select a published availability slot."
    except Exception as e:
        logger.error('failed_to_fetch_doctor_slots', extra={'error': str(e)})
        return "Doctor schedule service unavailable"


def _validate_slot_times(slot_start, slot_end):
    """Common slot validation: duration (≥30 min, multiple of 30), clinic hours, lead time."""
    duration_minutes = (slot_end - slot_start).total_seconds() / 60
    if duration_minutes < SLOT_DURATION_MINUTES:
        return f"Slot duration must be at least {SLOT_DURATION_MINUTES} minutes"
    if duration_minutes % SLOT_DURATION_MINUTES != 0:
        return f"Slot duration must be a multiple of {SLOT_DURATION_MINUTES} minutes (e.g. 30, 60, 90)"

    if slot_start.time() < CLINIC_OPEN or slot_end.time() > CLINIC_CLOSE:
        return (f"Slot must be within clinic hours "
                f"{CLINIC_OPEN.strftime('%I:%M %p')} – {CLINIC_CLOSE.strftime('%I:%M %p')}")

    min_booking_time = datetime.utcnow() + timedelta(hours=LEAD_TIME_BOOK_HOURS)
    if slot_start < min_booking_time:
        return f"Slot must be at least {LEAD_TIME_BOOK_HOURS} hours from now (UTC)"

    return None


def _check_doctor_overlap(doctor_id, slot_start, slot_end, exclude_appt_id=None):
    """Check for SCHEDULED/NO_SHOW overlapping appointment for this doctor."""
    q = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.slot_start < slot_end,
        Appointment.slot_end   > slot_start,
        Appointment.status.in_(['SCHEDULED', 'NO_SHOW']),
    )
    if exclude_appt_id:
        q = q.filter(Appointment.id != exclude_appt_id)
    if q.first():
        return "Slot is not available: doctor already has an appointment in this time slot"
    return None


def _check_patient_overlap(patient_id, slot_start, slot_end, exclude_appt_id=None):
    """Ensure a patient cannot have two overlapping active appointments."""
    q = Appointment.query.filter(
        Appointment.patient_id == patient_id,
        Appointment.slot_start < slot_end,
        Appointment.slot_end   > slot_start,
        Appointment.status.in_(['SCHEDULED']),
    )
    if exclude_appt_id:
        q = q.filter(Appointment.id != exclude_appt_id)
    if q.first():
        return "Patient already has an appointment overlapping this time slot"
    return None


def _check_doctor_daily_capacity(doctor_id, slot_start, doctor_data):
    """Ensure doctor has not hit max_appointments_per_day for the slot's date."""
    max_cap = doctor_data.get('max_appointments_per_day', 20)
    slot_date = slot_start.date()
    count = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.status == 'SCHEDULED',
        db.func.date(Appointment.slot_start) == slot_date.isoformat(),
    ).count()
    if count >= max_cap:
        return (f"Doctor has reached the maximum of {max_cap} appointments "
                f"for {slot_date.isoformat()}")
    return None


def _trigger_billing(appointment, bill_type='completion', cancellation_policy=None):
    """Fire-and-forget billing trigger. Errors are logged but do not fail the caller."""
    try:
        payload = {
            'appointment_id': appointment.id,
            'patient_id':     appointment.patient_id,
            'bill_type':      bill_type,
        }
        if cancellation_policy:
            payload['cancellation_policy'] = cancellation_policy
        requests.post(f"{BILLING_SERVICE_URL}/bills/internal/trigger",
                      json=payload, timeout=3)
    except Exception as exc:
        logger.warning('billing_trigger_failed', extra={
            'appointment_id': appointment.id, 'error': str(exc)
        })


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/appointments', methods=['POST'])
def create_appointment():
    data = request.get_json(force=True) or {}
    missing = [f for f in ('patient_id', 'doctor_id', 'department', 'slot_start', 'slot_end')
               if not data.get(f)]
    if missing:
        return jsonify({'error': f"Missing fields: {', '.join(missing)}"}), 400

    if data.get('id') and db.session.get(Appointment, int(data['id'])):
        return jsonify({'error': 'Appointment already exists'}), 409

    # ── Parse datetimes ───────────────────────────────────────────────────────
    try:
        slot_start = datetime.fromisoformat(data['slot_start'])
        slot_end   = datetime.fromisoformat(data['slot_end'])
    except ValueError:
        return jsonify({'error': 'Invalid datetime format. Use ISO 8601'}), 400

    if slot_end <= slot_start:
        return jsonify({'error': 'slot_end must be after slot_start'}), 400

    # ── Slot time validations ─────────────────────────────────────────────────
    slot_err = _validate_slot_times(slot_start, slot_end)
    if slot_err:
        return jsonify({'error': slot_err}), 400

    # ── Cross-service: patient active ─────────────────────────────────────────
    ok, err, _ = _verify_patient(data['patient_id'])
    if not ok:
        return jsonify({'error': err}), 404 if 'not found' in err else (400 if 'inactive' in err else 503)

    # ── Cross-service: doctor active + department match ───────────────────────
    ok, err, doctor_data = _verify_doctor(data['doctor_id'], department=data['department'])
    if not ok:
        return jsonify({'error': err}), 404 if 'not found' in err else (400 if 'inactive' in err or 'mismatch' in err else 503)

    # ── Doctor daily capacity ─────────────────────────────────────────────────
    cap_err = _check_doctor_daily_capacity(int(data['doctor_id']), slot_start, doctor_data)
    if cap_err:
        return jsonify({'error': cap_err}), 409

    # ── Doctor published availability ─────────────────────────────────────────
    avail_err = _verify_doctor_published_slot(int(data['doctor_id']), slot_start, slot_end)
    if avail_err:
        return jsonify({'error': avail_err}), 409

    # ── Doctor overlap ────────────────────────────────────────────────────────
    doc_overlap = _check_doctor_overlap(int(data['doctor_id']), slot_start, slot_end)
    if doc_overlap:
        return jsonify({'error': doc_overlap}), 409

    # ── Patient overlap ───────────────────────────────────────────────────────
    pat_overlap = _check_patient_overlap(int(data['patient_id']), slot_start, slot_end)
    if pat_overlap:
        return jsonify({'error': pat_overlap}), 409

    appt = Appointment(
        id=int(data['id']) if data.get('id') else None,
        patient_id=int(data['patient_id']),
        doctor_id=int(data['doctor_id']),
        department=data['department'],
        slot_start=slot_start, slot_end=slot_end,
        status='SCHEDULED',
        reschedule_count=0,
        version=1,
        notes=data.get('notes'),
    )
    db.session.add(appt)
    db.session.commit()
    APPOINTMENTS_CREATED.inc()
    logger.info('appointment_booked', extra={
        'appointment_id': appt.id, 'patient_id': appt.patient_id,
        'doctor_id': appt.doctor_id, 'status': appt.status,
    })
    return jsonify(appt.to_dict()), 201


@app.route('/appointments', methods=['GET'])
def list_appointments():
    q = Appointment.query
    if request.args.get('patient_id'):
        q = q.filter_by(patient_id=int(request.args['patient_id']))
    if request.args.get('doctor_id'):
        q = q.filter_by(doctor_id=int(request.args['doctor_id']))
    if request.args.get('status'):
        q = q.filter_by(status=request.args['status'].upper())
    return jsonify([a.to_dict() for a in q.all()])


@app.route('/appointments/<int:appt_id>', methods=['GET'])
def get_appointment(appt_id):
    appt = db.session.get(Appointment, appt_id)
    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404
    return jsonify(appt.to_dict())


@app.route('/appointments/<int:appt_id>/status', methods=['PATCH', 'POST'])
def update_status(appt_id):
    """Generic status update — enforces the state machine.

    Supports PATCH for API clients and POST for compatibility with seed scripts or clients that cannot send PATCH.
    """
    appt = db.session.get(Appointment, appt_id)
    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404

    data   = request.get_json(force=True) or {}
    status = (data.get('status') or '').upper()
    if status not in VALID_STATUSES:
        return jsonify({'error': f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}"}), 400

    allowed = ALLOWED_TRANSITIONS.get(appt.status, set())
    if status not in allowed:
        return jsonify({
            'error': f"Cannot transition from {appt.status} to {status}",
            'allowed_transitions': sorted(allowed),
        }), 409

    appt.status = status
    appt.version += 1
    appt.updated_at = datetime.utcnow()
    if data.get('notes'):
        appt.notes = data['notes']
    db.session.commit()
    logger.info('appointment_status_updated', extra={
        'appointment_id': appt_id, 'new_status': status, 'version': appt.version,
    })
    return jsonify(appt.to_dict())


@app.route('/appointments/<int:appt_id>/reschedule', methods=['PATCH'])
def reschedule(appt_id):
    appt = db.session.get(Appointment, appt_id)
    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404
    if appt.status != 'SCHEDULED':
        return jsonify({'error': 'Only SCHEDULED appointments can be rescheduled'}), 409
    if appt.reschedule_count >= MAX_RESCHEDULES:
        return jsonify({'error': f'Maximum reschedules ({MAX_RESCHEDULES}) reached for this appointment'}), 409

    # ── 1-hour lead time: cannot reschedule within 1 h of current slot ────────
    now = datetime.utcnow()
    if now >= (appt.slot_start - timedelta(hours=LEAD_TIME_RESCHEDULE_H)):
        return jsonify({
            'error': f'Rescheduling is not allowed within {LEAD_TIME_RESCHEDULE_H} hour(s) of the scheduled slot'
        }), 409

    data = request.get_json(force=True) or {}
    missing = [f for f in ('slot_start', 'slot_end') if not data.get(f)]
    if missing:
        return jsonify({'error': f"Missing fields: {', '.join(missing)}"}), 400

    try:
        slot_start = datetime.fromisoformat(data['slot_start'])
        slot_end   = datetime.fromisoformat(data['slot_end'])
    except ValueError:
        return jsonify({'error': 'Invalid datetime format. Use ISO 8601'}), 400

    if slot_end <= slot_start:
        return jsonify({'error': 'slot_end must be after slot_start'}), 400

    # ── Slot validations (same rules as booking) ──────────────────────────────
    slot_err = _validate_slot_times(slot_start, slot_end)
    if slot_err:
        return jsonify({'error': slot_err}), 400

    # ── Doctor still active ───────────────────────────────────────────────────
    ok, err, doctor_data = _verify_doctor(appt.doctor_id)
    if not ok:
        return jsonify({'error': err}), 503

    # ── Doctor daily capacity on new date ─────────────────────────────────────
    cap_err = _check_doctor_daily_capacity(appt.doctor_id, slot_start, doctor_data)
    if cap_err:
        return jsonify({'error': cap_err}), 409

    # ── Doctor published availability ─────────────────────────────────────────
    avail_err = _verify_doctor_published_slot(appt.doctor_id, slot_start, slot_end)
    if avail_err:
        return jsonify({'error': avail_err}), 409

    # ── Doctor overlap on new slot (excluding current appt) ───────────────────
    doc_overlap = _check_doctor_overlap(appt.doctor_id, slot_start, slot_end,
                                        exclude_appt_id=appt_id)
    if doc_overlap:
        return jsonify({'error': doc_overlap}), 409

    # ── Patient overlap on new slot (excluding current appt) ─────────────────
    pat_overlap = _check_patient_overlap(appt.patient_id, slot_start, slot_end,
                                         exclude_appt_id=appt_id)
    if pat_overlap:
        return jsonify({'error': pat_overlap}), 409

    appt.slot_start       = slot_start
    appt.slot_end         = slot_end
    appt.reschedule_count += 1
    appt.version          += 1
    appt.updated_at        = datetime.utcnow()
    if data.get('notes'):
        appt.notes = data['notes']
    db.session.commit()
    logger.info('appointment_rescheduled', extra={
        'appointment_id': appt_id, 'doctor_id': appt.doctor_id,
        'reschedule_count': appt.reschedule_count, 'version': appt.version,
    })
    return jsonify(appt.to_dict())


@app.route('/appointments/<int:appt_id>/cancel', methods=['POST'])
def cancel_appointment(appt_id):
    """
    Cancel an appointment.
    Policy:
      - Cancellation > 2 h before slot → VOID bill (full refund)
      - Cancellation ≤ 2 h before slot → 50% cancellation charge
      - Cannot cancel a COMPLETED or already CANCELLED appointment.
    """
    appt = db.session.get(Appointment, appt_id)
    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404
    if appt.status not in ALLOWED_TRANSITIONS or 'CANCELLED' not in ALLOWED_TRANSITIONS.get(appt.status, set()):
        return jsonify({
            'error': f"Cannot cancel an appointment with status '{appt.status}'"
        }), 409

    now  = datetime.utcnow()
    hours_until_slot = (appt.slot_start - now).total_seconds() / 3600

    if hours_until_slot > LEAD_TIME_CANCEL_HOURS:
        cancellation_policy = 'FULL_REFUND'       # > 2 h → no charge
        charge_pct          = 0.0
    else:
        cancellation_policy = 'PARTIAL_CHARGE'    # ≤ 2 h → 50% charge
        charge_pct          = 0.50

    data = request.get_json(force=True) or {}

    appt.status     = 'CANCELLED'
    appt.version   += 1
    appt.updated_at = datetime.utcnow()
    if data.get('notes'):
        appt.notes = data['notes']
    db.session.commit()
    APPOINTMENTS_CANCELLED.inc()
    logger.info('appointment_cancelled', extra={
        'appointment_id': appt_id, 'cancellation_policy': cancellation_policy,
        'charge_pct': charge_pct, 'hours_until_slot': round(hours_until_slot, 2),
    })

    # Trigger billing with cancellation policy metadata
    _trigger_billing(appt, bill_type='cancellation',
                     cancellation_policy={
                         'policy':      cancellation_policy,
                         'charge_pct':  charge_pct,
                         'hours_until_slot': round(hours_until_slot, 2),
                     })

    return jsonify({
        **appt.to_dict(),
        'cancellation_policy': cancellation_policy,
        'charge_pct':          charge_pct,
        'message': (
            'Full refund — cancelled more than 2 hours before the slot.'
            if charge_pct == 0.0 else
            '50% cancellation charge applied — cancelled within 2 hours of the slot.'
        ),
    })


@app.route('/appointments/<int:appt_id>/complete', methods=['POST'])
def complete_appointment(appt_id):
    """
    Mark appointment COMPLETED and trigger billing.
    Bill = consultation_fee + medication_cost + 5% tax.
    """
    appt = db.session.get(Appointment, appt_id)
    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404
    if appt.status != 'SCHEDULED':
        return jsonify({'error': f"Only SCHEDULED appointments can be completed (current: {appt.status})"}), 409

    data = request.get_json(force=True) or {}

    appt.status     = 'COMPLETED'
    appt.version   += 1
    appt.updated_at = datetime.utcnow()
    if data.get('notes'):
        appt.notes = data['notes']
    db.session.commit()
    logger.info('appointment_completed', extra={'appointment_id': appt_id, 'version': appt.version})

    # _trigger_billing(appt, bill_type='completion') # Disabled per user request (manual UI billing instead)

    return jsonify({
        **appt.to_dict(),
        'message': 'Appointment marked COMPLETED.',
    })


@app.route('/appointments/<int:appt_id>/noshow', methods=['POST'])
def noshow_appointment(appt_id):
    """
    Mark appointment as NO_SHOW after the grace period (15 minutes post slot_start).
    Full consultation fee is charged; manual review may apply.
    """
    appt = db.session.get(Appointment, appt_id)
    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404
    if appt.status != 'SCHEDULED':
        return jsonify({'error': f"Only SCHEDULED appointments can be marked NO_SHOW (current: {appt.status})"}), 409

    # Enforce grace period: slot must have started at least NO_SHOW_GRACE_MINUTES ago
    now = datetime.utcnow()
    grace_boundary = appt.slot_start + timedelta(minutes=NO_SHOW_GRACE_MINUTES)
    if now < grace_boundary:
        remaining = int((grace_boundary - now).total_seconds() / 60)
        return jsonify({
            'error': (f"NO_SHOW can only be recorded after the {NO_SHOW_GRACE_MINUTES}-minute "
                      f"grace period. Please wait ~{remaining} more minute(s).")
        }), 409

    data = request.get_json(force=True) or {}

    appt.status     = 'NO_SHOW'
    appt.version   += 1
    appt.updated_at = datetime.utcnow()
    if data.get('notes'):
        appt.notes = data['notes']
    db.session.commit()
    logger.info('appointment_noshow', extra={'appointment_id': appt_id, 'version': appt.version})

    _trigger_billing(appt, bill_type='noshow',
                     cancellation_policy={'policy': 'NO_SHOW_FULL_CHARGE', 'charge_pct': 1.0})

    return jsonify({
        **appt.to_dict(),
        'message': 'Appointment marked NO_SHOW. Full consultation fee will be charged.',
    })


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    port = int(os.environ.get('PORT', 5003))
    app.run(host='0.0.0.0', port=port, debug=False)
