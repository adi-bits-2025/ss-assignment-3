from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Prescription(db.Model):
    __tablename__ = 'prescriptions'

    id             = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, nullable=False)
    patient_id     = db.Column(db.Integer, nullable=False)
    doctor_id      = db.Column(db.Integer, nullable=False)
    medication     = db.Column(db.String(200), nullable=False)
    dosage         = db.Column(db.String(100), nullable=False)
    days           = db.Column(db.Integer, nullable=False)
    issued_at      = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':             self.id,
            'appointment_id': self.appointment_id,
            'patient_id':     self.patient_id,
            'doctor_id':      self.doctor_id,
            'medication':     self.medication,
            'dosage':         self.dosage,
            'days':           self.days,
            'issued_at':      self.issued_at.isoformat() if self.issued_at else None,
        }
