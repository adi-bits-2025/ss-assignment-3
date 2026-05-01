import os
import time
import logging
from datetime import datetime

from flask import Flask, request, jsonify, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST

from models import db, Doctor, DoctorSlot

# ── App & DB ──────────────────────────────────────────────────────────────────
app = Flask(__name__)

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), 'data'))
os.makedirs(DATA_DIR, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(DATA_DIR, 'doctors.db')}"
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


logger = logging.getLogger('doctor-schedule-service')
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
DOCTORS_CREATED = Counter('doctors_registered_total', 'Total doctors registered')
SLOTS_CREATED   = Counter('doctor_slots_created_total', 'Total doctor slots created')


@app.before_request
def _start_timer():
    g.t0 = time.time()


@app.after_request
def _log_request(resp):
    dur = round((time.time() - g.t0) * 1000, 2)
    REQUEST_COUNT.labels('doctor-schedule-service', request.method,
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
    return jsonify({'status': 'ok', 'service': 'doctor-schedule-service'})


SWAGGER_UI_HTML = """
<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Doctor Schedule Service API Docs</title>
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
        'info': {'title': 'Doctor Schedule Service API', 'version': '1.0.0'},
        'servers': [{'url': request.host_url.rstrip('/')}],
        'paths': {
            '/health': {
                'get': {'summary': 'Health check', 'responses': {'200': {'description': 'OK'}}}
            },
            '/doctors': {
                'get': {'summary': 'List doctors', 'responses': {'200': {'description': 'OK'}}},
                'post': {
                    'summary': 'Create doctor',
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
            '/doctors/{doctor_id}': {
                'get': {
                    'summary': 'Get doctor',
                    'parameters': [{'name': 'doctor_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'responses': {'200': {'description': 'OK'}, '404': {'description': 'Not found'}}
                },
                'put': {
                    'summary': 'Update doctor',
                    'parameters': [{'name': 'doctor_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'requestBody': {
                        'required': True,
                        'content': {'application/json': {'schema': {'type': 'object'}}}
                    },
                    'responses': {'200': {'description': 'Updated'}, '404': {'description': 'Not found'}}
                },
                'delete': {
                    'summary': 'Delete doctor',
                    'parameters': [{'name': 'doctor_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'responses': {'200': {'description': 'Deleted'}, '404': {'description': 'Not found'}}
                }
            },
            '/doctors/{doctor_id}/slots': {
                'get': {
                    'summary': 'List doctor slots',
                    'parameters': [{'name': 'doctor_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'responses': {'200': {'description': 'OK'}, '404': {'description': 'Not found'}}
                },
                'post': {
                    'summary': 'Add doctor slot',
                    'parameters': [{'name': 'doctor_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'requestBody': {
                        'required': True,
                        'content': {'application/json': {'schema': {'type': 'object'}}}
                    },
                    'responses': {
                        '201': {'description': 'Created'},
                        '400': {'description': 'Validation error'},
                        '404': {'description': 'Not found'}
                    }
                }
            },
            '/doctors/{doctor_id}/slots/{slot_id}': {
                'delete': {
                    'summary': 'Delete doctor slot',
                    'parameters': [
                        {'name': 'doctor_id', 'in': 'path', 'required': True,
                         'schema': {'type': 'integer'}},
                        {'name': 'slot_id', 'in': 'path', 'required': True,
                         'schema': {'type': 'integer'}}
                    ],
                    'responses': {'200': {'description': 'Deleted'}, '404': {'description': 'Not found'}}
                }
            }
        }
    })


@app.route('/swagger')
def swagger_ui():
    return SWAGGER_UI_HTML, 200, {'Content-Type': 'text/html; charset=utf-8'}

# ── Doctor Routes ─────────────────────────────────────────────────────────────
@app.route('/doctors', methods=['POST'])
def create_doctor():
    data = request.get_json(force=True) or {}
    missing = [f for f in ('name', 'email', 'phone', 'department', 'specialization')
               if not data.get(f)]
    if missing:
        return jsonify({'error': f"Missing fields: {', '.join(missing)}"}), 400

    if Doctor.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already registered'}), 409
    if data.get('id') and db.session.get(Doctor, int(data['id'])):
        return jsonify({'error': 'Doctor already exists'}), 409

    doctor = Doctor(
        id=int(data['id']) if data.get('id') else None,
        name=data['name'], email=data['email'], phone=str(data['phone']),
        department=data['department'], specialization=data['specialization'],
    )
    db.session.add(doctor)
    db.session.commit()
    DOCTORS_CREATED.inc()
    logger.info('doctor_created', extra={'doctor_id': doctor.id,
                                         'email': doctor.email,
                                         'phone': doctor.phone})
    return jsonify(doctor.to_dict()), 201


@app.route('/doctors', methods=['GET'])
def list_doctors():
    dept = request.args.get('department')
    q = Doctor.query
    if dept:
        q = q.filter_by(department=dept)
    return jsonify([d.to_dict() for d in q.all()])


@app.route('/doctors/<int:doctor_id>', methods=['GET'])
def get_doctor(doctor_id):
    doctor = db.session.get(Doctor, doctor_id)
    if not doctor:
        return jsonify({'error': 'Doctor not found'}), 404
    return jsonify(doctor.to_dict())


@app.route('/doctors/<int:doctor_id>', methods=['PUT'])
def update_doctor(doctor_id):
    doctor = db.session.get(Doctor, doctor_id)
    if not doctor:
        return jsonify({'error': 'Doctor not found'}), 404

    data = request.get_json(force=True) or {}
    for field in ('name', 'phone', 'department', 'specialization'):
        if field in data:
            setattr(doctor, field, str(data[field]))
    if 'email' in data:
        existing = Doctor.query.filter_by(email=data['email']).first()
        if existing and existing.id != doctor_id:
            return jsonify({'error': 'Email already in use'}), 409
        doctor.email = data['email']
    db.session.commit()
    return jsonify(doctor.to_dict())


@app.route('/doctors/<int:doctor_id>', methods=['DELETE'])
def delete_doctor(doctor_id):
    doctor = db.session.get(Doctor, doctor_id)
    if not doctor:
        return jsonify({'error': 'Doctor not found'}), 404
    db.session.delete(doctor)
    db.session.commit()
    return jsonify({'message': f'Doctor {doctor_id} deleted'})

# ── Slot Routes ───────────────────────────────────────────────────────────────
@app.route('/doctors/<int:doctor_id>/slots', methods=['POST'])
def add_slot(doctor_id):
    doctor = db.session.get(Doctor, doctor_id)
    if not doctor:
        return jsonify({'error': 'Doctor not found'}), 404

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

    slot = DoctorSlot(doctor_id=doctor_id, slot_start=slot_start,
                      slot_end=slot_end, is_available=True)
    db.session.add(slot)
    db.session.commit()
    SLOTS_CREATED.inc()
    logger.info('slot_created', extra={'doctor_id': doctor_id, 'slot_id': slot.id})
    return jsonify(slot.to_dict()), 201


@app.route('/doctors/<int:doctor_id>/slots', methods=['GET'])
def list_slots(doctor_id):
    doctor = db.session.get(Doctor, doctor_id)
    if not doctor:
        return jsonify({'error': 'Doctor not found'}), 404
    only_available = request.args.get('available', 'false').lower() == 'true'
    q = DoctorSlot.query.filter_by(doctor_id=doctor_id)
    if only_available:
        q = q.filter_by(is_available=True)
    return jsonify([s.to_dict() for s in q.all()])


@app.route('/doctors/<int:doctor_id>/slots/<int:slot_id>', methods=['DELETE'])
def delete_slot(doctor_id, slot_id):
    slot = DoctorSlot.query.filter_by(id=slot_id, doctor_id=doctor_id).first()
    if not slot:
        return jsonify({'error': 'Slot not found'}), 404
    db.session.delete(slot)
    db.session.commit()
    return jsonify({'message': f'Slot {slot_id} deleted'})

# ── Seed ──────────────────────────────────────────────────────────────────────
# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    port = int(os.environ.get('PORT', 5002))
    app.run(host='0.0.0.0', port=port, debug=False)
