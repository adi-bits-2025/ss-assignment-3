import os
import time
import logging
from datetime import date, datetime

from flask import Flask, request, jsonify, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

from models import db, Patient

# ── App & DB ──────────────────────────────────────────────────────────────────
app = Flask(__name__)

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), 'data'))
os.makedirs(DATA_DIR, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(DATA_DIR, 'patients.db')}"
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

# ── JSON Logging ──────────────────────────────────────────────────────────────
def _mask_email(val):
    if not val or '@' not in str(val):
        return val
    local, rest = str(val).split('@', 1)
    parts = rest.split('.')
    masked_domain = f"{parts[0][0]}***" if parts else '***'
    return f"{local[0]}***@{masked_domain}.{parts[-1]}"

def _mask_phone(val):
    s = str(val)
    return f"{'*' * max(0, len(s) - 4)}{s[-4:]}" if len(s) > 4 else '****'


class _MaskFilter(logging.Filter):
    def filter(self, record):
        if getattr(record, 'email', None):
            record.email = _mask_email(record.email)
        if getattr(record, 'phone', None):
            record.phone = _mask_phone(record.phone)
        return True


logger = logging.getLogger('patient-service')
logger.setLevel(logging.INFO)
_h = logging.StreamHandler()
_h.setFormatter(jsonlogger.JsonFormatter('%(asctime)s %(name)s %(levelname)s %(message)s'))
_h.addFilter(_MaskFilter())
logger.addHandler(_h)
logger.propagate = False

# ── Prometheus ────────────────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    'http_requests_total', 'Total HTTP requests',
    ['service', 'method', 'endpoint', 'status']
)
PATIENTS_CREATED = Counter('patients_registered_total', 'Total patients registered')


@app.before_request
def _start_timer():
    g.t0 = time.time()


@app.after_request
def _log_request(resp):
    dur = round((time.time() - g.t0) * 1000, 2)
    REQUEST_COUNT.labels('patient-service', request.method,
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
    return jsonify({'status': 'ok', 'service': 'patient-service'})


SWAGGER_UI_HTML = """
<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Patient Service API Docs</title>
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
        'info': {'title': 'Patient Service API', 'version': '1.0.0'},
        'servers': [{'url': request.host_url.rstrip('/')}],
        'paths': {
            '/health': {
                'get': {'summary': 'Health check', 'responses': {'200': {'description': 'OK'}}}
            },
            '/patients': {
                'get': {'summary': 'List patients', 'responses': {'200': {'description': 'OK'}}},
                'post': {
                    'summary': 'Create patient',
                    'requestBody': {
                        'required': True,
                        'content': {'application/json': {'schema': {'type': 'object'}}}
                    },
                    'responses': {
                        '201': {'description': 'Created'},
                        '400': {'description': 'Validation error'},
                        '409': {'description': 'Duplicate email'}
                    }
                }
            },
            '/patients/{patient_id}': {
                'get': {
                    'summary': 'Get patient',
                    'parameters': [{'name': 'patient_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'responses': {'200': {'description': 'OK'}, '404': {'description': 'Not found'}}
                },
                'put': {
                    'summary': 'Update patient',
                    'parameters': [{'name': 'patient_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'requestBody': {
                        'required': True,
                        'content': {'application/json': {'schema': {'type': 'object'}}}
                    },
                    'responses': {'200': {'description': 'Updated'}, '404': {'description': 'Not found'}}
                },
                'delete': {
                    'summary': 'Deactivate patient (soft-delete)',
                    'parameters': [{'name': 'patient_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'responses': {'200': {'description': 'Deactivated'}, '404': {'description': 'Not found'}}
                }
            },
            '/patients/{patient_id}/activate': {
                'patch': {
                    'summary': 'Reactivate a deactivated patient',
                    'parameters': [{'name': 'patient_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'responses': {'200': {'description': 'Activated'}, '404': {'description': 'Not found'}}
                }
            }
        }
    })


@app.route('/swagger')
def swagger_ui():
    return SWAGGER_UI_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/patients', methods=['POST'])
def create_patient():
    data = request.get_json(force=True) or {}
    missing = [f for f in ('name', 'email', 'phone') if not data.get(f)]
    if missing:
        return jsonify({'error': f"Missing fields: {', '.join(missing)}"}), 400

    if Patient.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already registered'}), 409
    if data.get('id') and db.session.get(Patient, int(data['id'])):
        return jsonify({'error': 'Patient already exists'}), 409

    dob = None
    if data.get('dob'):
        try:
            dob = date.fromisoformat(data['dob'])
        except ValueError:
            return jsonify({'error': 'Invalid dob format, expected YYYY-MM-DD'}), 400

    patient = Patient(
        id=int(data['id']) if data.get('id') else None,
        name=data['name'], email=data['email'],
        phone=str(data['phone']), dob=dob,
        is_active=True,
    )
    db.session.add(patient)
    db.session.commit()
    PATIENTS_CREATED.inc()
    logger.info('patient_created', extra={'patient_id': patient.id,
                                          'email': patient.email,
                                          'phone': patient.phone})
    return jsonify(patient.to_dict()), 201


@app.route('/patients', methods=['GET'])
def list_patients():
    q = Patient.query
    # Support ?active=true/false filter
    active_param = request.args.get('active')
    if active_param is not None:
        q = q.filter_by(is_active=(active_param.lower() == 'true'))
    return jsonify([p.to_dict() for p in q.all()])


@app.route('/patients/<int:patient_id>', methods=['GET'])
def get_patient(patient_id):
    patient = db.session.get(Patient, patient_id)
    if not patient:
        return jsonify({'error': 'Patient not found'}), 404
    return jsonify(patient.to_dict())


@app.route('/patients/<int:patient_id>', methods=['PUT'])
def update_patient(patient_id):
    patient = db.session.get(Patient, patient_id)
    if not patient:
        return jsonify({'error': 'Patient not found'}), 404

    data = request.get_json(force=True) or {}
    if 'name' in data:
        patient.name = data['name']
    if 'phone' in data:
        patient.phone = str(data['phone'])
    if 'email' in data:
        existing = Patient.query.filter_by(email=data['email']).first()
        if existing and existing.id != patient_id:
            return jsonify({'error': 'Email already in use'}), 409
        patient.email = data['email']
    if 'dob' in data:
        try:
            patient.dob = date.fromisoformat(data['dob']) if data['dob'] else None
        except ValueError:
            return jsonify({'error': 'Invalid dob format, expected YYYY-MM-DD'}), 400

    patient.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(patient.to_dict())


@app.route('/patients/<int:patient_id>', methods=['DELETE'])
def deactivate_patient(patient_id):
    """Soft-delete: marks patient as inactive, preserving history."""
    patient = db.session.get(Patient, patient_id)
    if not patient:
        return jsonify({'error': 'Patient not found'}), 404
    if not patient.is_active:
        return jsonify({'error': 'Patient is already inactive'}), 409
    patient.is_active = False
    patient.updated_at = datetime.utcnow()
    db.session.commit()
    logger.info('patient_deactivated', extra={'patient_id': patient_id})
    return jsonify({'message': f'Patient {patient_id} deactivated', **patient.to_dict()})


@app.route('/patients/<int:patient_id>/activate', methods=['PATCH'])
def activate_patient(patient_id):
    """Re-activate a previously deactivated patient."""
    patient = db.session.get(Patient, patient_id)
    if not patient:
        return jsonify({'error': 'Patient not found'}), 404
    if patient.is_active:
        return jsonify({'error': 'Patient is already active'}), 409
    patient.is_active = True
    patient.updated_at = datetime.utcnow()
    db.session.commit()
    logger.info('patient_activated', extra={'patient_id': patient_id})
    return jsonify({'message': f'Patient {patient_id} activated', **patient.to_dict()})

# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
