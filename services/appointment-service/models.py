from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

VALID_STATUSES = {'SCHEDULED', 'COMPLETED', 'CANCELLED'}


class Appointment(db.Model):
    __tablename__ = 'appointments'

    id         = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, nullable=False)
    doctor_id  = db.Column(db.Integer, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    slot_start = db.Column(db.DateTime, nullable=False)
    slot_end   = db.Column(db.DateTime, nullable=False)
    status     = db.Column(db.String(20), nullable=False, default='SCHEDULED')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':         self.id,
            'patient_id': self.patient_id,
            'doctor_id':  self.doctor_id,
            'department': self.department,
            'slot_start': self.slot_start.isoformat() if self.slot_start else None,
            'slot_end':   self.slot_end.isoformat() if self.slot_end else None,
            'status':     self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
