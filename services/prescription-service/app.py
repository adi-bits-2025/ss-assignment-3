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

from models import db, Prescription

# ── App & DB ──────────────────────────────────────────────────────────────────
app = Flask(__name__)

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), 'data'))
os.makedirs(DATA_DIR, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(DATA_DIR, 'prescriptions.db')}"
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
APPOINTMENT_SERVICE_URL = os.environ.get('APPOINTMENT_SERVICE_URL', 'http://localhost:5003')

# ── JSON Logging ──────────────────────────────────────────────────────────────
logger = logging.getLogger('prescription-service')
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
PRESCRIPTIONS_ISSUED = Counter('prescriptions_issued_total', 'Total prescriptions issued')


@app.before_request
def _start_timer():
    g.t0 = time.time()


@app.after_request
def _log_request(resp):
    dur = round((time.time() - g.t0) * 1000, 2)
    REQUEST_COUNT.labels('prescription-service', request.method,
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
    return jsonify({'status': 'ok', 'service': 'prescription-service'})


SWAGGER_UI_HTML = """
<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Prescription Service API Docs</title>
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
        'info': {'title': 'Prescription Service API', 'version': '1.0.0'},
        'servers': [{'url': request.host_url.rstrip('/')}],
        'paths': {
            '/health': {
                'get': {'summary': 'Health check', 'responses': {'200': {'description': 'OK'}}}
            },
            '/prescriptions': {
                'get': {'summary': 'List prescriptions', 'responses': {'200': {'description': 'OK'}}},
                'post': {
                    'summary': 'Create prescription',
                    'requestBody': {
                        'required': True,
                        'content': {'application/json': {'schema': {'type': 'object'}}}
                    },
                    'responses': {
                        '201': {'description': 'Created'},
                        '400': {'description': 'Validation error'},
                        '404': {'description': 'Related resource not found'},
                        '409': {'description': 'Invalid appointment state'},
                        '503': {'description': 'Dependency unavailable'}
                    }
                }
            },
            '/prescriptions/{rx_id}': {
                'get': {
                    'summary': 'Get prescription',
                    'parameters': [{'name': 'rx_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'responses': {'200': {'description': 'OK'}, '404': {'description': 'Not found'}}
                }
            },
            '/prescriptions/appointment/{appointment_id}': {
                'get': {
                    'summary': 'List by appointment',
                    'parameters': [{'name': 'appointment_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'responses': {'200': {'description': 'OK'}}
                }
            },
            '/prescriptions/patient/{patient_id}': {
                'get': {
                    'summary': 'List by patient',
                    'parameters': [{'name': 'patient_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'responses': {'200': {'description': 'OK'}}
                }
            }
        }
    })


@app.route('/swagger')
def swagger_ui():
    return SWAGGER_UI_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}

# ── Helpers ───────────────────────────────────────────────────────────────────
def _verify_appointment(appointment_id):
    try:
        resp = requests.get(f"{APPOINTMENT_SERVICE_URL}/appointments/{appointment_id}", timeout=5)
        if resp.status_code == 404:
            return None, f"Appointment {appointment_id} not found"
        resp.raise_for_status()
        return resp.json(), None
    except requests.exceptions.ConnectionError:
        return None, "Appointment service unavailable"
    except requests.exceptions.Timeout:
        return None, "Appointment service timed out"

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/prescriptions', methods=['POST'])
def create_prescription():
    data = request.get_json(force=True) or {}
    missing = [f for f in ('appointment_id', 'patient_id', 'doctor_id', 'medication', 'dosage', 'days')
               if not data.get(f)]
    if missing:
        return jsonify({'error': f"Missing fields: {', '.join(missing)}"}), 400

    # Cross-service validation
    appt, err = _verify_appointment(data['appointment_id'])
    if err:
        code = 404 if 'not found' in err else 503
        return jsonify({'error': err}), code

    if appt.get('status') not in ('SCHEDULED', 'COMPLETED'):
        return jsonify({'error': 'Prescriptions can only be issued for active appointments'}), 409

    try:
        days = int(data['days'])
        if days <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'error': 'days must be a positive integer'}), 400

    rx = Prescription(
        appointment_id=int(data['appointment_id']),
        patient_id=int(data['patient_id']),
        doctor_id=int(data['doctor_id']),
        medication=data['medication'],
        dosage=data['dosage'],
        days=days,
    )
    db.session.add(rx)
    db.session.commit()
    PRESCRIPTIONS_ISSUED.inc()
    logger.info('prescription_issued', extra={
        'prescription_id': rx.id, 'appointment_id': rx.appointment_id,
        'patient_id': rx.patient_id, 'medication': rx.medication,
    })
    return jsonify(rx.to_dict()), 201


@app.route('/prescriptions', methods=['GET'])
def list_prescriptions():
    return jsonify([rx.to_dict() for rx in Prescription.query.all()])


@app.route('/prescriptions/<int:rx_id>', methods=['GET'])
def get_prescription(rx_id):
    rx = db.session.get(Prescription, rx_id)
    if not rx:
        return jsonify({'error': 'Prescription not found'}), 404
    return jsonify(rx.to_dict())


@app.route('/prescriptions/appointment/<int:appointment_id>', methods=['GET'])
def by_appointment(appointment_id):
    items = Prescription.query.filter_by(appointment_id=appointment_id).all()
    return jsonify([rx.to_dict() for rx in items])


@app.route('/prescriptions/patient/<int:patient_id>', methods=['GET'])
def by_patient(patient_id):
    items = Prescription.query.filter_by(patient_id=patient_id).all()
    return jsonify([rx.to_dict() for rx in items])

# ── Seed ──────────────────────────────────────────────────────────────────────
def seed_data():
    if Prescription.query.count() > 0:
        return
    csv_dir = os.environ.get(
        'CSV_DIR',
        os.path.join(os.path.dirname(__file__), '..', '..', 'doc', 'HMS Dataset (1)')
    )
    csv_path = os.path.join(csv_dir, 'hms_prescriptions_indian.csv')
    if not os.path.exists(csv_path):
        logger.warning('seed_skipped', extra={'reason': f'CSV not found: {csv_path}'})
        return
    with open(csv_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                issued = datetime.fromisoformat(row['issued_at'])
            except (ValueError, KeyError):
                issued = datetime.utcnow()
            db.session.execute(text(
                "INSERT OR IGNORE INTO prescriptions"
                " (id, appointment_id, patient_id, doctor_id, medication, dosage, days, issued_at)"
                " VALUES (:id, :appointment_id, :patient_id, :doctor_id, :medication, :dosage, :days, :issued_at)"
            ), {
                'id': int(row['prescription_id']),
                'appointment_id': int(row['appointment_id']),
                'patient_id': int(row['patient_id']),
                'doctor_id': int(row['doctor_id']),
                'medication': row['medication'],
                'dosage': row['dosage'],
                'days': int(row['days']),
                'issued_at': issued.isoformat(),
            })
    db.session.commit()
    logger.info('seed_complete', extra={'table': 'prescriptions'})

# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_data()
    port = int(os.environ.get('PORT', 5004))
    app.run(host='0.0.0.0', port=port, debug=False)
