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

from models import db, Bill, Payment, VALID_BILL_STATUSES, VALID_PAYMENT_METHODS

# ── App & DB ──────────────────────────────────────────────────────────────────
app = Flask(__name__)

DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.path.dirname(__file__), 'data'))
os.makedirs(DATA_DIR, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(DATA_DIR, 'billing.db')}"
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
PATIENT_SERVICE_URL     = os.environ.get('PATIENT_SERVICE_URL',     'http://localhost:5001')
APPOINTMENT_SERVICE_URL = os.environ.get('APPOINTMENT_SERVICE_URL', 'http://localhost:5003')

# ── JSON Logging ──────────────────────────────────────────────────────────────
logger = logging.getLogger('billing-service')
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
BILLS_CREATED   = Counter('bills_created_total', 'Total bills created')
PAYMENTS_MADE   = Counter('payments_recorded_total', 'Total payments recorded')


@app.before_request
def _start_timer():
    g.t0 = time.time()


@app.after_request
def _log_request(resp):
    dur = round((time.time() - g.t0) * 1000, 2)
    REQUEST_COUNT.labels('billing-service', request.method,
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
    return jsonify({'status': 'ok', 'service': 'billing-service'})


SWAGGER_UI_HTML = """
<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Billing Service API Docs</title>
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
        'info': {'title': 'Billing Service API', 'version': '1.0.0'},
        'servers': [{'url': request.host_url.rstrip('/')}],
        'paths': {
            '/health': {
                'get': {'summary': 'Health check', 'responses': {'200': {'description': 'OK'}}}
            },
            '/bills': {
                'get': {'summary': 'List bills', 'responses': {'200': {'description': 'OK'}}},
                'post': {
                    'summary': 'Create bill',
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
            '/bills/{bill_id}': {
                'get': {
                    'summary': 'Get bill',
                    'parameters': [{'name': 'bill_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'responses': {'200': {'description': 'OK'}, '404': {'description': 'Not found'}}
                }
            },
            '/bills/{bill_id}/status': {
                'patch': {
                    'summary': 'Update bill status',
                    'parameters': [{'name': 'bill_id', 'in': 'path', 'required': True,
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
            '/bills/{bill_id}/payments': {
                'get': {
                    'summary': 'List bill payments',
                    'parameters': [{'name': 'bill_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'responses': {'200': {'description': 'OK'}, '404': {'description': 'Not found'}}
                },
                'post': {
                    'summary': 'Add payment',
                    'parameters': [{'name': 'bill_id', 'in': 'path', 'required': True,
                                    'schema': {'type': 'integer'}}],
                    'requestBody': {
                        'required': True,
                        'content': {'application/json': {'schema': {'type': 'object'}}}
                    },
                    'responses': {
                        '201': {'description': 'Created'},
                        '400': {'description': 'Validation error'},
                        '404': {'description': 'Not found'},
                        '409': {'description': 'Invalid state transition'}
                    }
                }
            },
            '/bills/patient/{patient_id}': {
                'get': {
                    'summary': 'List bills by patient',
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
def _verify_patient(patient_id):
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


def _verify_appointment(appointment_id):
    try:
        resp = requests.get(f"{APPOINTMENT_SERVICE_URL}/appointments/{appointment_id}", timeout=5)
        if resp.status_code == 404:
            return False, f"Appointment {appointment_id} not found"
        resp.raise_for_status()
        return True, None
    except requests.exceptions.ConnectionError:
        return False, "Appointment service unavailable"
    except requests.exceptions.Timeout:
        return False, "Appointment service timed out"

# ── Bill Routes ───────────────────────────────────────────────────────────────
@app.route('/bills', methods=['POST'])
def create_bill():
    data = request.get_json(force=True) or {}
    missing = [f for f in ('patient_id', 'appointment_id', 'amount') if not data.get(f)]
    if missing:
        return jsonify({'error': f"Missing fields: {', '.join(missing)}"}), 400

    try:
        amount = float(data['amount'])
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'error': 'amount must be a positive number'}), 400

    ok, err = _verify_patient(data['patient_id'])
    if not ok:
        return jsonify({'error': err}), 404 if 'not found' in err else 503

    ok, err = _verify_appointment(data['appointment_id'])
    if not ok:
        return jsonify({'error': err}), 404 if 'not found' in err else 503

    bill = Bill(
        patient_id=int(data['patient_id']),
        appointment_id=int(data['appointment_id']),
        amount=amount,
        status='OPEN',
    )
    db.session.add(bill)
    db.session.commit()
    BILLS_CREATED.inc()
    logger.info('bill_created', extra={
        'bill_id': bill.id, 'patient_id': bill.patient_id,
        'appointment_id': bill.appointment_id, 'amount': bill.amount,
    })
    return jsonify(bill.to_dict()), 201


@app.route('/bills', methods=['GET'])
def list_bills():
    q = Bill.query
    if request.args.get('patient_id'):
        q = q.filter_by(patient_id=int(request.args['patient_id']))
    if request.args.get('status'):
        q = q.filter_by(status=request.args['status'].upper())
    return jsonify([b.to_dict() for b in q.all()])


@app.route('/bills/<int:bill_id>', methods=['GET'])
def get_bill(bill_id):
    bill = db.session.get(Bill, bill_id)
    if not bill:
        return jsonify({'error': 'Bill not found'}), 404
    return jsonify(bill.to_dict())


@app.route('/bills/patient/<int:patient_id>', methods=['GET'])
def bills_by_patient(patient_id):
    return jsonify([b.to_dict() for b in Bill.query.filter_by(patient_id=patient_id).all()])


@app.route('/bills/<int:bill_id>/status', methods=['PATCH'])
def update_bill_status(bill_id):
    bill = db.session.get(Bill, bill_id)
    if not bill:
        return jsonify({'error': 'Bill not found'}), 404

    data   = request.get_json(force=True) or {}
    status = (data.get('status') or '').upper()
    if status not in VALID_BILL_STATUSES:
        return jsonify({'error': f"Invalid status. Must be one of: {', '.join(VALID_BILL_STATUSES)}"}), 400

    if bill.status == 'PAID':
        return jsonify({'error': 'Cannot update a paid bill'}), 409

    bill.status = status
    db.session.commit()
    logger.info('bill_status_updated', extra={'bill_id': bill_id, 'status': status})
    return jsonify(bill.to_dict())

# ── Payment Routes ────────────────────────────────────────────────────────────
@app.route('/bills/<int:bill_id>/payments', methods=['POST'])
def add_payment(bill_id):
    bill = db.session.get(Bill, bill_id)
    if not bill:
        return jsonify({'error': 'Bill not found'}), 404
    if bill.status in ('PAID', 'VOID'):
        return jsonify({'error': f"Cannot add payment to a {bill.status} bill"}), 409

    data = request.get_json(force=True) or {}
    missing = [f for f in ('amount', 'method') if not data.get(f)]
    if missing:
        return jsonify({'error': f"Missing fields: {', '.join(missing)}"}), 400

    method = str(data['method']).upper()
    if method not in VALID_PAYMENT_METHODS:
        return jsonify({'error': f"Invalid method. Must be one of: {', '.join(VALID_PAYMENT_METHODS)}"}), 400

    try:
        amount = float(data['amount'])
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'error': 'amount must be a positive number'}), 400

    payment = Payment(bill_id=bill_id, amount=amount, method=method)
    db.session.add(payment)

    # Sum all payments to determine if bill is fully paid
    total_paid = sum(p.amount for p in bill.payments) + amount
    if total_paid >= bill.amount:
        bill.status = 'PAID'

    db.session.commit()
    PAYMENTS_MADE.inc()
    logger.info('payment_recorded', extra={
        'payment_id': payment.id, 'bill_id': bill_id,
        'amount': amount, 'method': method, 'bill_status': bill.status,
    })
    return jsonify({**payment.to_dict(), 'bill_status': bill.status}), 201


@app.route('/bills/<int:bill_id>/payments', methods=['GET'])
def list_payments(bill_id):
    bill = db.session.get(Bill, bill_id)
    if not bill:
        return jsonify({'error': 'Bill not found'}), 404
    return jsonify([p.to_dict() for p in bill.payments])

# ── Seed ──────────────────────────────────────────────────────────────────────
def seed_data():
    if Bill.query.count() > 0:
        return
    csv_dir = os.environ.get(
        'CSV_DIR',
        os.path.join(os.path.dirname(__file__), '..', '..', 'doc', 'HMS Dataset (1)')
    )

    bills_path    = os.path.join(csv_dir, 'hms_bills_indian.csv')
    payments_path = os.path.join(csv_dir, 'hms_payments_indian.csv')

    if os.path.exists(bills_path):
        with open(bills_path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                try:
                    created = datetime.fromisoformat(row['created_at'])
                except (ValueError, KeyError):
                    created = datetime.utcnow()
                db.session.execute(text(
                    "INSERT OR IGNORE INTO bills"
                    " (id, patient_id, appointment_id, amount, status, created_at)"
                    " VALUES (:id, :patient_id, :appointment_id, :amount, :status, :created_at)"
                ), {
                    'id': int(row['bill_id']),
                    'patient_id': int(row['patient_id']),
                    'appointment_id': int(row['appointment_id']),
                    'amount': float(row['amount']),
                    'status': row.get('status', 'OPEN'),
                    'created_at': created.isoformat(),
                })
        db.session.commit()
        logger.info('seed_complete', extra={'table': 'bills'})
    else:
        logger.warning('seed_skipped', extra={'reason': f'CSV not found: {bills_path}'})

    if os.path.exists(payments_path):
        with open(payments_path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                try:
                    paid_at = datetime.fromisoformat(row['paid_at'])
                except (ValueError, KeyError):
                    paid_at = datetime.utcnow()
                db.session.execute(text(
                    "INSERT OR IGNORE INTO payments"
                    " (id, bill_id, amount, method, paid_at)"
                    " VALUES (:id, :bill_id, :amount, :method, :paid_at)"
                ), {
                    'id': int(row['payment_id']),
                    'bill_id': int(row['bill_id']),
                    'amount': float(row['amount']),
                    'method': row.get('method', 'CASH'),
                    'paid_at': paid_at.isoformat(),
                })
        db.session.commit()
        logger.info('seed_complete', extra={'table': 'payments'})
    else:
        logger.warning('seed_skipped', extra={'reason': f'CSV not found: {payments_path}'})

# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_data()
    port = int(os.environ.get('PORT', 5005))
    app.run(host='0.0.0.0', port=port, debug=False)
