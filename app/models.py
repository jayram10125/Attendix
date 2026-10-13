from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import UniqueConstraint
from . import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="employee")
    department = db.Column(db.String(120), default="")
    active = db.Column(db.Boolean, nullable=False, default=True)
    manager_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    manager = db.relationship("User", remote_side=[id], foreign_keys=[manager_id])
    location = db.relationship("Location", foreign_keys=[location_id])

    @property
    def is_active(self):
        return self.active


class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    radius_m = db.Column(db.Integer, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)


class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), unique=True, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    grace_minutes = db.Column(db.Integer, nullable=False, default=15)
    working_days = db.Column(db.String(20), nullable=False, default="0,1,2,3,4")
    location = db.relationship("Location")


class FaceIdentity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    face_data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class Attendance(db.Model):
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_attendance_user_date"),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    check_in = db.Column(db.DateTime(timezone=True))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    type = db.Column(db.String(20), nullable=False, default="onsite")
    status = db.Column(db.String(20), nullable=False, default="present")
    distance_m = db.Column(db.Float)
    request_id = db.Column(db.Integer, db.ForeignKey("exception_request.id"), unique=True)
    user = db.relationship("User", foreign_keys=[user_id])


class ExceptionRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    type = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    status = db.Column(db.String(20), nullable=False, default="pending")
    manager_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    reviewed_at = db.Column(db.DateTime(timezone=True))
    review_note = db.Column(db.Text)
    user = db.relationship("User", foreign_keys=[user_id])
    manager = db.relationship("User", foreign_keys=[manager_id])


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    action = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

