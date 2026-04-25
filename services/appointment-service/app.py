import os
import csv
import time
import logging
from datetime import datetime

import requests
from flask import Flask, request, jsonify, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, event
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

from models import db, Appointment, VALID_STATUSES

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
PATIENT_SERVICE_URL = os.environ.get('PATIENT_SERVICE_URL', 'http://localhost:5001')
DOCTOR_SERVICE_URL  = os.environ.get('DOCTOR_SERVICE_URL',  'http://localhost:5002')

# ── JSON Logging ──────────────────────────────────────────────────────────────
logger = logging.getLogger('appointment-service')
logger.setLevel(logging.INFO)
_h = logging.StreamHandler()
_h.setFormatter(jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s'))
logger.addHandler(_h)
logger.propagate = False

# ── Prometheus ────────────────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    'http_requests_total', 'Total HTTP requests',
    ['service', 'method', 'endpoint', 'status']
)
APPOINTMENTS_CREATED = Counter('appointments_created_total', 'Total appointments booked')
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
<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Appointment Service API Docs</title>
    <link rel=\"stylesheet\" href=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui.css\" />
    <style>body { margin: 0; } #swagger-ui { max-width: 1100px; margin: 0 auto; }</style>
  </head>
  <body>
    <div id=\"swagger-ui\"></div>
    <script src=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js\"></script>
    <script>
      window.onload = function () {
        SwaggerUIBundle({
          url: '/swagger.json',
          dom_id: '#swagger-ui'
        });
      };
    </script>
  </body>
</html>
"""


@app.route('/swagger.json')
def swagger_json():
    return jsonify({
        'openapi': '3.0.3',
        'info': {'title': 'Appointment Service API', 'version': '1.0.0'},
        'servers': [{'url': request.host_url.rstrip('/')}],
        'paths': {
            '/health': {
                'get': {'summary': 'Health check', 'responses': {'200': {'description': 'OK'}}}
            },
            '/appointments': {
                'get': {'summary': 'List appointments', 'responses': {'200': {'description': 'OK'}}},
                'post': {
                    'summary': 'Create appointment',
                    'requestBody': {
                        'required': True,
                        'content': {'application/json': {'schema': {'type': 'object'}}}
                    },
                    'responses': {
                        '201': {'description': 'Created'},
                        '400': {'description': 'Validation error'},
                        '404': {'description': 'Related resource not found'},
                        '503': {'description': 'Dependency unavailable'}
                    }
                }
            },
            '/appointments/{appt_id}': {
                'get': {
                    'summary': 'Get appointment',
                    'parameters': [{'name': 'appt_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'responses': {'200': {'description': 'OK'}, '404': {'description': 'Not found'}}
                }
            },
            '/appointments/{appt_id}/status': {
                'patch': {
                    'summary': 'Update appointment status',
                    'parameters': [{'name': 'appt_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'requestBody': {
                        'required': True,
                        'content': {'application/json': {'schema': {'type': 'object'}}}
                    },
                    'responses': {
                        '200': {'description': 'Updated'},
                        '400': {'description': 'Validation error'},
                        '404': {'description': 'Not found'},
                        '409': {'description': 'Invalid state transition'}
                    }
                }
            },
            '/appointments/{appt_id}/reschedule': {
                'patch': {
                    'summary': 'Reschedule appointment',
                    'parameters': [{'name': 'appt_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'requestBody': {
                        'required': True,
                        'content': {'application/json': {'schema': {'type': 'object'}}}
                    },
                    'responses': {
                        '200': {'description': 'Updated'},
                        '400': {'description': 'Validation error'},
                        '404': {'description': 'Not found'},
                        '409': {'description': 'Invalid state transition'},
                        '503': {'description': 'Dependency unavailable'}
                    }
                }
            }
        }
    })


@app.route('/swagger')
def swagger_ui():
    return SWAGGER_UI_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}

# ── Helpers ───────────────────────────────────────────────────────────────────
def _verify_patient(patient_id):
    """Returns (ok: bool, error_msg: str|None)."""
    try:
        resp = requests.get(f"{PATIENT_SERVICE_URL}/patients/{patient_id}", timeout=5)
        if resp.status_code == 404:
            return False, f"Patient {patient_id} not found"
        resp.raise_for_status()
        return True, None
    except requests.exceptions.ConnectionError:
        return False, "Patient service unavailable"
    except requests.exceptions.Timeout:
        return False, "Patient service timed out"


def _verify_doctor(doctor_id):
    """Returns (ok: bool, error_msg: str|None)."""
    try:
        resp = requests.get(f"{DOCTOR_SERVICE_URL}/doctors/{doctor_id}", timeout=5)
        if resp.status_code == 404:
            return False, f"Doctor {doctor_id} not found"
        resp.raise_for_status()
        return True, None
    except requests.exceptions.ConnectionError:
        return False, "Doctor schedule service unavailable"
    except requests.exceptions.Timeout:
        return False, "Doctor schedule service timed out"

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/appointments', methods=['POST'])
def create_appointment():
    data = request.get_json(force=True) or {}
    missing = [f for f in ('patient_id', 'doctor_id', 'department', 'slot_start', 'slot_end')
               if not data.get(f)]
    if missing:
        return jsonify({'error': f"Missing fields: {', '.join(missing)}"}), 400

    # Cross-service validation
    ok, err = _verify_patient(data['patient_id'])
    if not ok:
        return jsonify({'error': err}), 404 if 'not found' in err else 503

    ok, err = _verify_doctor(data['doctor_id'])
    if not ok:
        return jsonify({'error': err}), 404 if 'not found' in err else 503

    try:
        slot_start = datetime.fromisoformat(data['slot_start'])
        slot_end   = datetime.fromisoformat(data['slot_end'])
    except ValueError:
        return jsonify({'error': 'Invalid datetime format. Use ISO 8601'}), 400

    if slot_end <= slot_start:
        return jsonify({'error': 'slot_end must be after slot_start'}), 400

    appt = Appointment(
        patient_id=int(data['patient_id']),
        doctor_id=int(data['doctor_id']),
        department=data['department'],
        slot_start=slot_start, slot_end=slot_end,
        status='SCHEDULED',
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


@app.route('/appointments/<int:appt_id>/status', methods=['PATCH'])
def update_status(appt_id):
    appt = db.session.get(Appointment, appt_id)
    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404

    data   = request.get_json(force=True) or {}
    status = (data.get('status') or '').upper()
    if status not in VALID_STATUSES:
        return jsonify({'error': f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}"}), 400

    if appt.status == 'CANCELLED':
        return jsonify({'error': 'Cannot update a cancelled appointment'}), 409
    if appt.status == 'COMPLETED':
        return jsonify({'error': 'Cannot update a completed appointment'}), 409

    if status == 'CANCELLED':
        APPOINTMENTS_CANCELLED.inc()

    appt.status = status
    db.session.commit()
    logger.info('appointment_status_updated', extra={
        'appointment_id': appt_id, 'new_status': status,
    })
    return jsonify(appt.to_dict())


@app.route('/appointments/<int:appt_id>/reschedule', methods=['PATCH'])
def reschedule(appt_id):
    appt = db.session.get(Appointment, appt_id)
    if not appt:
        return jsonify({'error': 'Appointment not found'}), 404
    if appt.status != 'SCHEDULED':
        return jsonify({'error': 'Only SCHEDULED appointments can be rescheduled'}), 409

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

    # Verify doctor still exists before rescheduling
    ok, err = _verify_doctor(appt.doctor_id)
    if not ok:
        return jsonify({'error': err}), 503

    appt.slot_start = slot_start
    appt.slot_end   = slot_end
    db.session.commit()
    logger.info('appointment_rescheduled', extra={
        'appointment_id': appt_id, 'doctor_id': appt.doctor_id,
    })
    return jsonify(appt.to_dict())

# ── Seed ──────────────────────────────────────────────────────────────────────
def seed_data():
    if Appointment.query.count() > 0:
        return
    csv_dir = os.environ.get(
        'CSV_DIR',
        os.path.join(os.path.dirname(__file__), '..', '..', 'doc', 'HMS Dataset (1)')
    )
    csv_path = os.path.join(csv_dir, 'hms_appointments_indian.csv')
    if not os.path.exists(csv_path):
        logger.warning('seed_skipped', extra={'reason': f'CSV not found: {csv_path}'})
        return
    with open(csv_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                slot_start = datetime.fromisoformat(row['slot_start'])
                slot_end   = datetime.fromisoformat(row['slot_end'])
                created    = datetime.fromisoformat(row['created_at'])
            except (ValueError, KeyError):
                continue
            db.session.execute(text(
                "INSERT OR IGNORE INTO appointments"
                " (id, patient_id, doctor_id, department, slot_start, slot_end, status, created_at)"
                " VALUES (:id, :patient_id, :doctor_id, :department, :slot_start, :slot_end, :status, :created_at)"
            ), {
                'id': int(row['appointment_id']),
                'patient_id': int(row['patient_id']),
                'doctor_id': int(row['doctor_id']),
                'department': row['department'],
                'slot_start': slot_start.isoformat(),
                'slot_end': slot_end.isoformat(),
                'status': row.get('status', 'SCHEDULED'),
                'created_at': created.isoformat(),
            })
    db.session.commit()
    logger.info('seed_complete', extra={'table': 'appointments'})

# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_data()
    port = int(os.environ.get('PORT', 5003))
    app.run(host='0.0.0.0', port=port, debug=False)
