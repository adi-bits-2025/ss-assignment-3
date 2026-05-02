import os
import logging
import time

import requests
from flask import Flask, request, jsonify, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from models import (db, Bill, Payment, TAX_RATE,
                    VALID_BILL_STATUSES, VALID_PAYMENT_METHODS, BILL_TRANSITIONS)

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
REQUEST_COUNT   = Counter('http_requests_total', 'Total HTTP requests',
                          ['service', 'method', 'endpoint', 'status'])
BILLS_CREATED   = Counter('bills_created_total', 'Total bills created')
PAYMENTS_MADE   = Counter('payments_recorded_total', 'Total payments recorded')
PAYMENTS_FAILED = Counter('payments_failed_total', 'Total failed payment attempts')
BILL_CREATE_LATENCY = Histogram(
    'bill_creation_latency_ms', 'Bill creation latency in ms',
    buckets=[10, 50, 100, 250, 500, 1000, 2500]
)


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
<!doctype html><html><head><meta charset=\"utf-8\"/>
<title>Billing Service API Docs</title>
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
        'info': {'title': 'Billing Service API', 'version': '1.0.0'},
        'servers': [{'url': request.host_url.rstrip('/')}],
        'paths': {
            '/bills': {'get': {'summary': 'List bills'}, 'post': {'summary': 'Create bill'}},
            '/bills/{bill_id}': {'get': {'summary': 'Get bill'}},
            '/bills/{bill_id}/status': {'patch': {'summary': 'Update bill status (state-machine)'}},
            '/bills/{bill_id}/payments': {
                'get':  {'summary': 'List payments'},
                'post': {'summary': 'Add payment (idempotent via Idempotency-Key header)'}
            },
            '/bills/{bill_id}/refund': {'post': {'summary': 'Issue refund (partial or full)'}},
            '/bills/patient/{patient_id}': {'get': {'summary': 'List bills by patient'}},
            '/bills/appointment/{appointment_id}': {'get': {'summary': 'List bills by appointment'}},
            '/bills/internal/trigger': {'post': {'summary': 'Internal: triggered by appointment service'}},
            '/payments/charge': {'post': {'summary': 'Idempotent charge endpoint (Idempotency-Key header required)'}},
        }
    })


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verify_appointment(appointment_id):
    try:
        resp = requests.get(f"{APPOINTMENT_SERVICE_URL}/appointments/{appointment_id}", timeout=5)
        if resp.status_code == 404:
            return False, f"Appointment {appointment_id} not found", None
        resp.raise_for_status()
        return True, None, resp.json()
    except requests.exceptions.ConnectionError:
        return False, "Appointment service unavailable", None
    except requests.exceptions.Timeout:
        return False, "Appointment service timed out", None


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


def _compute_bill_amounts(consultation_fee, medication_cost):
    """Apply 5% tax and return (tax_amount, total_amount)."""
    tax   = round((consultation_fee + medication_cost) * TAX_RATE, 2)
    total = round(consultation_fee + medication_cost + tax, 2)
    return tax, total


def _active_bill_for_appointment(appointment_id):
    """Return any non-VOID bill for an appointment (at most one should exist)."""
    return Bill.query.filter(
        Bill.appointment_id == appointment_id,
        Bill.status != 'VOID',
    ).first()


# ── Bill Routes ───────────────────────────────────────────────────────────────

@app.route('/bills', methods=['POST'])
def create_bill():
    data = request.get_json(force=True) or {}
    missing = [f for f in ('appointment_id',) if not data.get(f)]
    if missing:
        return jsonify({'error': f"Missing fields: {', '.join(missing)}"}), 400

    if data.get('id') and db.session.get(Bill, int(data['id'])):
        return jsonify({'error': 'Bill already exists'}), 409

    # ── One active bill per appointment ───────────────────────────────────────
    existing = _active_bill_for_appointment(int(data['appointment_id']))
    if existing:
        return jsonify({
            'error': 'An active bill already exists for this appointment',
            'existing_bill_id': existing.id,
        }), 409

    ok, err, appt_data = _verify_appointment(data['appointment_id'])
    if not ok:
        return jsonify({'error': err}), 404 if 'not found' in err else 503

    appt_status = appt_data.get('status')

    # ── Fee fields ────────────────────────────────────────────────────────────
    try:
        consultation_fee = float(data.get('consultation_fee', 0) or 0)
        medication_cost  = float(data.get('medication_cost', 0) or 0)
        if consultation_fee < 0 or medication_cost < 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'error': 'consultation_fee and medication_cost must be non-negative numbers'}), 400

    bill_type           = 'completion'
    is_cancellation     = False
    cancellation_policy = None
    charge_pct_val      = None
    bill_status         = 'OPEN'

    if appt_status == 'COMPLETED':
        # Standard bill — require at least a consultation fee
        if consultation_fee <= 0:
            return jsonify({'error': 'consultation_fee is required and must be > 0 for COMPLETED appointments'}), 400
    else:
        return jsonify({
            'error': f"Bill can only be created for COMPLETED appointments. Current status: {appt_status}"
        }), 409

    patient_id = appt_data.get('patient_id')
    if not patient_id:
        return jsonify({'error': 'Appointment data missing patient_id'}), 500

    ok, err = _verify_patient(patient_id)
    if not ok:
        return jsonify({'error': err}), 404 if 'not found' in err else 503

    tax_amount, total_amount = _compute_bill_amounts(consultation_fee, medication_cost)

    t0   = time.time()
    bill = Bill(
        id=int(data['id']) if data.get('id') else None,
        patient_id=int(patient_id),
        appointment_id=int(data['appointment_id']),
        consultation_fee=consultation_fee,
        medication_cost=medication_cost,
        tax_amount=tax_amount,
        total_amount=total_amount,
        amount=total_amount,
        status=bill_status,
        is_cancellation=is_cancellation,
        cancellation_policy=cancellation_policy,
        charge_pct=charge_pct_val,
        bill_type=bill_type,
    )
    db.session.add(bill)
    db.session.commit()
    BILL_CREATE_LATENCY.observe((time.time() - t0) * 1000)
    BILLS_CREATED.inc()
    logger.info('bill_created', extra={
        'bill_id': bill.id, 'patient_id': bill.patient_id,
        'appointment_id': bill.appointment_id, 'total_amount': bill.total_amount,
        'bill_type': bill.bill_type, 'status': bill.status,
    })
    return jsonify(bill.to_dict()), 201


@app.route('/bills/internal/trigger', methods=['POST'])
def internal_trigger():
    """
    Internal endpoint called by Appointment Service after status changes.
    Creates the appropriate bill automatically using appointment metadata.
    Not a public API; no patient/appointment double-verification needed (already validated upstream).
    """
    data           = request.get_json(force=True) or {}
    appointment_id = data.get('appointment_id')
    patient_id     = data.get('patient_id')
    bill_type      = data.get('bill_type', 'completion')
    cancel_policy  = data.get('cancellation_policy') or {}

    if not appointment_id or not patient_id:
        return jsonify({'error': 'appointment_id and patient_id required'}), 400

    # Avoid duplicate bills
    existing = _active_bill_for_appointment(int(appointment_id))
    if existing:
        logger.info('billing_trigger_skipped_duplicate', extra={
            'appointment_id': appointment_id, 'existing_bill_id': existing.id
        })
        return jsonify({'skipped': True, 'existing_bill_id': existing.id}), 200

    charge_pct_val = float(cancel_policy.get('charge_pct', 0.0)) if cancel_policy else 0.0

    if bill_type == 'completion':
        # Sensible defaults — real fees should come via POST /bills
        consultation_fee = 500.0
        medication_cost  = 0.0
        status           = 'OPEN'
        is_cancellation  = False
        c_policy         = None
    elif bill_type == 'cancellation':
        consultation_fee = round(500.0 * charge_pct_val, 2)
        medication_cost  = 0.0
        status           = 'VOID' if charge_pct_val == 0.0 else 'OPEN'
        is_cancellation  = True
        c_policy         = cancel_policy.get('policy', 'FULL_REFUND')
    else:  # noshow
        consultation_fee = 500.0
        medication_cost  = 0.0
        status           = 'OPEN'
        is_cancellation  = True
        c_policy         = 'NO_SHOW_FULL_CHARGE'
        charge_pct_val   = 1.0

    tax_amount, total_amount = _compute_bill_amounts(consultation_fee, medication_cost)

    bill = Bill(
        patient_id=int(patient_id),
        appointment_id=int(appointment_id),
        consultation_fee=consultation_fee,
        medication_cost=medication_cost,
        tax_amount=tax_amount,
        total_amount=total_amount,
        amount=total_amount,
        status=status,
        is_cancellation=is_cancellation,
        cancellation_policy=c_policy,
        charge_pct=charge_pct_val,
        bill_type=bill_type,
    )
    db.session.add(bill)
    db.session.commit()
    BILLS_CREATED.inc()
    logger.info('bill_auto_created', extra={
        'bill_id': bill.id, 'appointment_id': appointment_id,
        'bill_type': bill_type, 'total_amount': bill.total_amount,
    })
    return jsonify(bill.to_dict()), 201


@app.route('/bills', methods=['GET'])
def list_bills():
    q = Bill.query
    if request.args.get('patient_id'):
        q = q.filter_by(patient_id=int(request.args['patient_id']))
    if request.args.get('status'):
        q = q.filter_by(status=request.args['status'].upper())
    if request.args.get('bill_type'):
        q = q.filter_by(bill_type=request.args['bill_type'].lower())
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


@app.route('/bills/appointment/<int:appointment_id>', methods=['GET'])
def bills_by_appointment(appointment_id):
    return jsonify([b.to_dict() for b in Bill.query.filter_by(appointment_id=appointment_id).all()])


@app.route('/bills/<int:bill_id>/status', methods=['PATCH'])
def update_bill_status(bill_id):
    bill = db.session.get(Bill, bill_id)
    if not bill:
        return jsonify({'error': 'Bill not found'}), 404

    data   = request.get_json(force=True) or {}
    status = (data.get('status') or '').upper()
    if status not in VALID_BILL_STATUSES:
        return jsonify({'error': f"Invalid status. Must be one of: {', '.join(sorted(VALID_BILL_STATUSES))}"}), 400

    allowed = BILL_TRANSITIONS.get(bill.status, set())
    if status not in allowed:
        return jsonify({
            'error': f"Cannot transition bill from '{bill.status}' to '{status}'",
            'allowed_transitions': sorted(allowed),
        }), 409

    bill.status     = status
    bill.updated_at = __import__('datetime').datetime.utcnow()
    db.session.commit()
    logger.info('bill_status_updated', extra={'bill_id': bill_id, 'status': status})
    return jsonify(bill.to_dict())


@app.route('/bills/<int:bill_id>/payments', methods=['POST'])
def add_payment(bill_id):
    bill = db.session.get(Bill, bill_id)
    if not bill:
        return jsonify({'error': 'Bill not found'}), 404
    if bill.status in ('PAID', 'VOID', 'FULL_REFUND'):
        PAYMENTS_FAILED.inc()
        return jsonify({'error': f"Cannot add payment to a {bill.status} bill"}), 409

    data = request.get_json(force=True) or {}

    # ── Idempotency — check header first, then body field ─────────────────────
    idempotency_key = (request.headers.get('Idempotency-Key')
                       or data.get('idempotency_key'))
    if idempotency_key:
        existing_payment = Payment.query.filter_by(idempotency_key=idempotency_key).first()
        if existing_payment:
            logger.info('payment_idempotent_replay', extra={
                'payment_id': existing_payment.id, 'idempotency_key': idempotency_key
            })
            return jsonify({
                **existing_payment.to_dict(),
                'bill_status': bill.status,
                'idempotent_replay': True,
            }), 200

    missing = [f for f in ('amount', 'method') if not data.get(f)]
    if missing:
        return jsonify({'error': f"Missing fields: {', '.join(missing)}"}), 400
    if data.get('id') and db.session.get(Payment, int(data['id'])):
        return jsonify({'error': 'Payment already exists'}), 409

    method = str(data['method']).upper()
    if method not in VALID_PAYMENT_METHODS:
        return jsonify({'error': f"Invalid method. Must be one of: {', '.join(sorted(VALID_PAYMENT_METHODS))}"}), 400

    try:
        amount = float(data['amount'])
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        PAYMENTS_FAILED.inc()
        return jsonify({'error': 'amount must be a positive number'}), 400

    payment = Payment(
        id=int(data['id']) if data.get('id') else None,
        bill_id=bill_id,
        amount=amount,
        method=method,
        idempotency_key=idempotency_key,
    )
    db.session.add(payment)

    total_paid = sum(p.amount for p in bill.payments) + amount
    if total_paid >= bill.total_amount:
        bill.status = 'PAID'

    db.session.commit()
    PAYMENTS_MADE.inc()
    logger.info('payment_recorded', extra={
        'payment_id': payment.id, 'bill_id': bill_id,
        'amount': amount, 'method': method, 'bill_status': bill.status,
        'idempotency_key': idempotency_key,
    })
    return jsonify({**payment.to_dict(), 'bill_status': bill.status}), 201


@app.route('/bills/<int:bill_id>/payments', methods=['GET'])
def list_payments(bill_id):
    bill = db.session.get(Bill, bill_id)
    if not bill:
        return jsonify({'error': 'Bill not found'}), 404
    return jsonify([p.to_dict() for p in bill.payments])


@app.route('/bills/<int:bill_id>/refund', methods=['POST'])
def refund_bill(bill_id):
    """
    Issue a refund on a PAID bill.
    Body: { "refund_type": "full" | "partial", "reason": "..." }
    Billing lifecycle: PAID → PARTIAL_REFUND | FULL_REFUND
    Edits to a paid bill are NOT allowed; use adjustments (this endpoint) instead.
    """
    bill = db.session.get(Bill, bill_id)
    if not bill:
        return jsonify({'error': 'Bill not found'}), 404
    if bill.status != 'PAID':
        return jsonify({'error': f"Refunds can only be issued on PAID bills (current: {bill.status})"}), 409

    data        = request.get_json(force=True) or {}
    refund_type = (data.get('refund_type') or 'full').lower()
    if refund_type not in ('full', 'partial'):
        return jsonify({'error': "refund_type must be 'full' or 'partial'"}), 400

    bill.status     = 'FULL_REFUND' if refund_type == 'full' else 'PARTIAL_REFUND'
    bill.updated_at = __import__('datetime').datetime.utcnow()
    db.session.commit()
    logger.info('bill_refunded', extra={
        'bill_id': bill_id, 'refund_type': refund_type, 'new_status': bill.status
    })
    return jsonify({**bill.to_dict(), 'refund_type': refund_type})


@app.route('/payments/charge', methods=['POST'])
def payments_charge():
    """
    Idempotent payment charge endpoint as per spec (/v1/payments/charge).
    Requires 'Idempotency-Key' header.
    Body: { "bill_id": int, "amount": float, "method": str }
    """
    idempotency_key = request.headers.get('Idempotency-Key')
    if not idempotency_key:
        return jsonify({'error': "'Idempotency-Key' header is required"}), 400

    # Check for replay
    existing_payment = Payment.query.filter_by(idempotency_key=idempotency_key).first()
    if existing_payment:
        bill = db.session.get(Bill, existing_payment.bill_id)
        return jsonify({
            **existing_payment.to_dict(),
            'bill_status': bill.status if bill else 'unknown',
            'idempotent_replay': True,
        }), 200

    data    = request.get_json(force=True) or {}
    missing = [f for f in ('bill_id', 'amount', 'method') if not data.get(f)]
    if missing:
        return jsonify({'error': f"Missing fields: {', '.join(missing)}"}), 400

    bill = db.session.get(Bill, int(data['bill_id']))
    if not bill:
        return jsonify({'error': 'Bill not found'}), 404
    if bill.status in ('PAID', 'VOID', 'FULL_REFUND'):
        return jsonify({'error': f"Cannot charge a {bill.status} bill"}), 409

    method = str(data['method']).upper()
    if method not in VALID_PAYMENT_METHODS:
        return jsonify({'error': f"Invalid method. Must be one of: {', '.join(sorted(VALID_PAYMENT_METHODS))}"}), 400

    try:
        amount = float(data['amount'])
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'error': 'amount must be a positive number'}), 400

    payment = Payment(
        bill_id=bill.id, amount=amount, method=method,
        idempotency_key=idempotency_key,
    )
    db.session.add(payment)

    total_paid = sum(p.amount for p in bill.payments) + amount
    if total_paid >= bill.total_amount:
        bill.status = 'PAID'

    db.session.commit()
    PAYMENTS_MADE.inc()
    logger.info('payment_charge', extra={
        'payment_id': payment.id, 'bill_id': bill.id,
        'amount': amount, 'bill_status': bill.status,
        'idempotency_key': idempotency_key,
    })
    return jsonify({**payment.to_dict(), 'bill_status': bill.status}), 201


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    port = int(os.environ.get('PORT', 5005))
    app.run(host='0.0.0.0', port=port, debug=False)
