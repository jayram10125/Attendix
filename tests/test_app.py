from datetime import datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import Attendance, FaceIdentity, Location, Schedule, User
from app.services import distance_m, schedule_status


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://", "SECRET_KEY": "test-secret", "WTF_CSRF_ENABLED": False})
    with app.app_context():
        db.create_all()
        location = Location(name="Campus", latitude=28.61, longitude=77.21, radius_m=200)
        db.session.add(location)
        db.session.flush()
        db.session.add(Schedule(location_id=location.id, start_time=time(9), end_time=time(18), working_days="0,1,2,3,4,5,6"))
        db.session.add(User(name="Admin", email="admin@test.com", password_hash=generate_password_hash("password12345"), role="admin"))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def face():
    return np.random.default_rng(42).integers(0, 256, (160, 160), dtype=np.uint8)


def admin_login(client):
    return client.post("/login", data={"email": "admin@test.com", "password": "password12345"}, follow_redirects=True)


def register_student(client, face, name="New Student"):
    admin_login(client)
    with patch("app.routes.extract_face", return_value=face):
        response = client.post("/admin/users", data={
            "name": name, "department": "BCA", "location_id": "1",
            "photos": '["photo1","photo2","photo3"]',
        }, follow_redirects=True)
    assert b"registered with face and location" in response.data
    client.post("/logout")


def test_public_page_and_admin_only_login(app, client):
    assert b"Mark attendance" in client.get("/").data
    assert b"Mark attendance" in client.get("/attendance").data
    assert client.get("/admin/users").status_code == 302
    with app.app_context():
        location = db.session.query(Location).first()
        db.session.add(User(name="Legacy Student", email="legacy@test.com", password_hash=generate_password_hash("password12345"), role="employee", location_id=location.id))
        db.session.commit()
    response = client.post("/login", data={"email": "legacy@test.com", "password": "password12345"})
    assert b"Invalid credentials" in response.data
    assert b"Super admin login" in client.get("/login").data


def test_admin_registers_student_with_face_and_location(app, client, face):
    register_student(client, face)
    with app.app_context():
        student = db.session.query(User).filter_by(name="New Student").first()
        identity = db.session.query(FaceIdentity).filter_by(user_id=student.id).first()
        assert student.role == "employee" and student.location_id == 1
        assert identity.face_data.startswith(b"ATTENDIX_FACES_V1\n")
    assert client.get("/face").status_code == 404


def test_public_face_attendance_checks_range_and_duplicates(app, client, face):
    register_student(client, face)
    moment = datetime(2026, 10, 13, 9, 10, tzinfo=ZoneInfo("Asia/Kolkata"))
    with patch("app.routes.local_now", return_value=moment), patch("app.routes.extract_face", return_value=face):
        outside = client.post("/attendance", data={"latitude": "29.61", "longitude": "77.21", "photo": "photo"}, follow_redirects=True)
        assert b"not in the range" in outside.data
        with app.app_context():
            assert db.session.query(Attendance).count() == 0
        success = client.post("/attendance", data={"latitude": "28.61", "longitude": "77.21", "photo": "photo"}, follow_redirects=True)
        assert b"Attendance marked for New Student" in success.data
        duplicate = client.post("/attendance", data={"latitude": "28.61", "longitude": "77.21", "photo": "photo"}, follow_redirects=True)
        assert b"already marked for today" in duplicate.data
    with app.app_context():
        assert db.session.query(Attendance).count() == 1


def test_unknown_face_is_rejected(app, client, face):
    register_student(client, face)
    different = np.random.default_rng(99).integers(0, 256, (160, 160), dtype=np.uint8)
    with patch("app.routes.local_now", return_value=datetime(2026, 10, 13, 9, 10, tzinfo=ZoneInfo("Asia/Kolkata"))), patch("app.routes.extract_face", return_value=different):
        response = client.post("/attendance", data={"latitude": "28.61", "longitude": "77.21", "photo": "photo"}, follow_redirects=True)
    assert b"not recognized" in response.data
    with app.app_context():
        assert db.session.query(Attendance).count() == 0


def test_multiple_registered_faces_identify_correct_student(app, client, face):
    other = np.random.default_rng(123).integers(0, 256, (160, 160), dtype=np.uint8)
    register_student(client, face)
    register_student(client, other, name="Other Student")
    with patch("app.routes.local_now", return_value=datetime(2026, 10, 13, 9, 10, tzinfo=ZoneInfo("Asia/Kolkata"))), patch("app.routes.extract_face", return_value=other):
        response = client.post("/attendance", data={"latitude": "28.61", "longitude": "77.21", "photo": "photo"}, follow_redirects=True)
    assert b"Attendance marked for Other Student" in response.data
    with app.app_context():
        row = db.session.query(Attendance).one()
        assert row.user.name == "Other Student"


def test_schedule_and_admin_pages(app, client):
    assert distance_m(28.61, 77.21, 28.61, 77.21) == 0
    with app.app_context():
        schedule = db.session.query(Schedule).first()
        assert schedule_status(schedule, datetime(2026, 10, 13, 9, 30, tzinfo=ZoneInfo("Asia/Kolkata"))) == "late"
        with pytest.raises(ValueError):
            schedule_status(schedule, datetime(2026, 10, 13, 19, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    admin_login(client)
    for path in ("/dashboard", "/admin/users", "/admin/locations", "/history", "/reports", "/profile"):
        assert client.get(path).status_code == 200, path
