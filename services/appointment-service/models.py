from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# NO_SHOW added per spec: reception marks appointment as NO_SHOW after grace period
VALID_STATUSES = {'SCHEDULED', 'COMPLETED', 'CANCELLED', 'NO_SHOW'}

# Allowed status transitions — enforces the appointment lifecycle state machine
# Key = current status, Value = set of statuses it can transition to
ALLOWED_TRANSITIONS = {
    'SCHEDULED':  {'COMPLETED', 'CANCELLED', 'NO_SHOW'},
    'COMPLETED':  set(),          # terminal state
    'CANCELLED':  set(),          # terminal state
    'NO_SHOW':    set(),          # terminal state
}


class Appointment(db.Model):
    __tablename__ = 'appointments'

    id               = db.Column(db.Integer, primary_key=True)
    patient_id       = db.Column(db.Integer, nullable=False)
    doctor_id        = db.Column(db.Integer, nullable=False)
    department       = db.Column(db.String(100), nullable=False)
    slot_start       = db.Column(db.DateTime, nullable=False)
    slot_end         = db.Column(db.DateTime, nullable=False)
    status           = db.Column(db.String(20), nullable=False, default='SCHEDULED')
    reschedule_count = db.Column(db.Integer, default=0, nullable=False)
    # Optimistic locking — incremented on every state change or reschedule
    version          = db.Column(db.Integer, default=1, nullable=False)
    notes            = db.Column(db.Text, nullable=True)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id':               self.id,
            'patient_id':       self.patient_id,
            'doctor_id':        self.doctor_id,
            'department':       self.department,
            'slot_start':       self.slot_start.isoformat() if self.slot_start else None,
            'slot_end':         self.slot_end.isoformat() if self.slot_end else None,
            'status':           self.status,
            'reschedule_count': self.reschedule_count,
            'version':          self.version,
            'notes':            self.notes,
            'created_at':       self.created_at.isoformat() if self.created_at else None,
            'updated_at':       self.updated_at.isoformat() if self.updated_at else None,
        }
