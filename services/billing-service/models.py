from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# Billing lifecycle: OPEN → PAID → PARTIAL_REFUND | FULL_REFUND
#                    OPEN → VOID  (for cancelled appointments with no charge)
VALID_BILL_STATUSES   = {'OPEN', 'PAID', 'VOID', 'PARTIAL_REFUND', 'FULL_REFUND'}
VALID_PAYMENT_METHODS = {'UPI', 'CARD', 'CASH', 'INSURANCE'}

# Allowed bill status transitions (state machine)
BILL_TRANSITIONS = {
    'OPEN':          {'PAID', 'VOID'},
    'PAID':          {'PARTIAL_REFUND', 'FULL_REFUND'},
    'VOID':          set(),           # terminal
    'PARTIAL_REFUND': set(),          # terminal
    'FULL_REFUND':   set(),           # terminal
}

TAX_RATE = 0.05   # 5% tax on consultation + medication


class Bill(db.Model):
    __tablename__ = 'bills'

    id                  = db.Column(db.Integer, primary_key=True)
    patient_id          = db.Column(db.Integer, nullable=False)
    appointment_id      = db.Column(db.Integer, nullable=False)
    # Fee breakdown
    consultation_fee    = db.Column(db.Float, nullable=False, default=0.0)
    medication_cost     = db.Column(db.Float, nullable=False, default=0.0)
    tax_amount          = db.Column(db.Float, nullable=False, default=0.0)
    total_amount        = db.Column(db.Float, nullable=False, default=0.0)
    # Legacy field kept for backward compat; equals total_amount
    amount              = db.Column(db.Float, nullable=False, default=0.0)
    status              = db.Column(db.String(20), nullable=False, default='OPEN')
    # Cancellation metadata
    is_cancellation     = db.Column(db.Boolean, default=False, nullable=False)
    cancellation_policy = db.Column(db.String(50), nullable=True)   # e.g. FULL_REFUND / PARTIAL_CHARGE / NO_SHOW_FULL_CHARGE
    charge_pct          = db.Column(db.Float, nullable=True)         # 0.0, 0.5, or 1.0
    # Bill type: 'completion' | 'cancellation' | 'noshow'
    bill_type           = db.Column(db.String(20), nullable=False, default='completion')
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at          = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    payments = db.relationship('Payment', backref='bill', lazy=True,
                               cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id':                  self.id,
            'patient_id':          self.patient_id,
            'appointment_id':      self.appointment_id,
            'consultation_fee':    self.consultation_fee,
            'medication_cost':     self.medication_cost,
            'tax_amount':          self.tax_amount,
            'total_amount':        self.total_amount,
            'amount':              self.amount,
            'status':              self.status,
            'is_cancellation':     self.is_cancellation,
            'cancellation_policy': self.cancellation_policy,
            'charge_pct':          self.charge_pct,
            'bill_type':           self.bill_type,
            'created_at':          self.created_at.isoformat() if self.created_at else None,
            'updated_at':          self.updated_at.isoformat() if self.updated_at else None,
        }


class Payment(db.Model):
    __tablename__ = 'payments'

    id               = db.Column(db.Integer, primary_key=True)
    bill_id          = db.Column(db.Integer, db.ForeignKey('bills.id'), nullable=False)
    amount           = db.Column(db.Float, nullable=False)
    method           = db.Column(db.String(20), nullable=False)
    # Idempotency key — unique per payment intent; duplicate keys return the same payment
    idempotency_key  = db.Column(db.String(128), nullable=True, unique=True)
    paid_at          = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':              self.id,
            'bill_id':         self.bill_id,
            'amount':          self.amount,
            'method':          self.method,
            'idempotency_key': self.idempotency_key,
            'paid_at':         self.paid_at.isoformat() if self.paid_at else None,
        }
