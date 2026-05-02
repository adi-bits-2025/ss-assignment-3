from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Doctor(db.Model):
    __tablename__ = 'doctors'

    id                      = db.Column(db.Integer, primary_key=True)
    name                    = db.Column(db.String(100), nullable=False)
    email                   = db.Column(db.String(120), unique=True, nullable=False)
    phone                   = db.Column(db.String(20), nullable=False)
    department              = db.Column(db.String(100), nullable=False)
    specialization          = db.Column(db.String(100), nullable=False)
    is_active               = db.Column(db.Boolean, default=True, nullable=False)
    # Maximum SCHEDULED appointments allowed per calendar day for this doctor.
    max_appointments_per_day = db.Column(db.Integer, default=20, nullable=False)
    created_at              = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at              = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    slots = db.relationship('DoctorSlot', backref='doctor', lazy=True,
                            cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id':                       self.id,
            'name':                     self.name,
            'email':                    self.email,
            'phone':                    self.phone,
            'department':               self.department,
            'specialization':           self.specialization,
            'is_active':                self.is_active,
            'max_appointments_per_day': self.max_appointments_per_day,
            'created_at':               self.created_at.isoformat() if self.created_at else None,
            'updated_at':               self.updated_at.isoformat() if self.updated_at else None,
        }


class DoctorSlot(db.Model):
    __tablename__ = 'doctor_slots'

    id           = db.Column(db.Integer, primary_key=True)
    doctor_id    = db.Column(db.Integer, db.ForeignKey('doctors.id'), nullable=False)
    slot_start   = db.Column(db.DateTime, nullable=False)
    slot_end     = db.Column(db.DateTime, nullable=False)
    is_available = db.Column(db.Boolean, default=True, nullable=False)

    def to_dict(self):
        return {
            'id':           self.id,
            'doctor_id':    self.doctor_id,
            'slot_start':   self.slot_start.isoformat() if self.slot_start else None,
            'slot_end':     self.slot_end.isoformat() if self.slot_end else None,
            'is_available': self.is_available,
        }
