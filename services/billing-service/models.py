from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

VALID_BILL_STATUSES    = {'OPEN', 'PAID', 'VOID'}
VALID_PAYMENT_METHODS  = {'UPI', 'CARD', 'CASH'}


class Bill(db.Model):
    __tablename__ = 'bills'

    id             = db.Column(db.Integer, primary_key=True)
    patient_id     = db.Column(db.Integer, nullable=False)
    appointment_id = db.Column(db.Integer, nullable=False)
    amount         = db.Column(db.Float, nullable=False)
    status         = db.Column(db.String(10), nullable=False, default='OPEN')
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    payments = db.relationship('Payment', backref='bill', lazy=True,
                               cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id':             self.id,
            'patient_id':     self.patient_id,
            'appointment_id': self.appointment_id,
            'amount':         self.amount,
            'status':         self.status,
            'created_at':     self.created_at.isoformat() if self.created_at else None,
        }


class Payment(db.Model):
    __tablename__ = 'payments'

    id      = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bills.id'), nullable=False)
    amount  = db.Column(db.Float, nullable=False)
    method  = db.Column(db.String(10), nullable=False)
    paid_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':      self.id,
            'bill_id': self.bill_id,
            'amount':  self.amount,
            'method':  self.method,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
        }
