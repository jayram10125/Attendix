from datetime import date, datetime, time, timezone
from functools import wraps
import json
import secrets
from uuid import uuid4

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .models import Attendance, AuditLog, FaceIdentity, Location, Schedule, User
from .services import distance_m, extract_face, local_now, match_registered_face, schedule_status, serialize_faces, validate_coordinates

bp = Blueprint("main", __name__)


def roles(*allowed):
    def decorate(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in allowed:
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def audit(action, description):
    db.session.add(AuditLog(user_id=current_user.id, action=action, description=description))


def save_or_error(message="Database operation failed. Try again."):
    try:
        db.session.commit()
        return True
    except (IntegrityError, SQLAlchemyError):
        db.session.rollback()
        flash(message, "danger")
        return False


@bp.app_errorhandler(403)
def forbidden(_):
    return render_template("error.html", title="Access denied", message="You do not have access to this page."), 403


@bp.app_errorhandler(404)
def missing(_):
    return render_template("error.html", title="Page not found", message="The requested page does not exist."), 404


@bp.route("/", methods=["GET", "POST"])
@bp.route("/attendance", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        try:
            moment = local_now()
            face = extract_face(request.form.get("photo"))
            identities = db.session.query(FaceIdentity).join(User, FaceIdentity.user_id == User.id).filter(User.active.is_(True), User.role == "employee").all()
            user_id = match_registered_face(identities, face)
            if user_id is None:
                raise ValueError("Registered face not recognized. Please try again.")
            student = db.session.get(User, user_id)
            if not student.location or not student.location.active:
                raise ValueError("Your assigned attendance location is unavailable. Contact admin.")
            lat, lon = validate_coordinates(request.form.get("latitude"), request.form.get("longitude"))
            distance = distance_m(lat, lon, student.location.latitude, student.location.longitude)
            if distance > student.location.radius_m:
                raise ValueError("You are not in the range of your assigned location.")
            schedule = db.session.query(Schedule).filter_by(location_id=student.location_id).first()
            if not schedule:
                raise ValueError("Your location has no schedule. Contact admin.")
            status = schedule_status(schedule, moment)
            if db.session.query(Attendance).filter_by(user_id=student.id, date=moment.date()).first():
                raise ValueError("Attendance already marked for today.")
            db.session.add(Attendance(user_id=student.id, date=moment.date(), check_in=moment.astimezone(timezone.utc), latitude=lat, longitude=lon, type="onsite", status=status, distance_m=distance))
            db.session.add(AuditLog(user_id=student.id, action="attendance", description="Public face check-in for " + moment.date().isoformat()))
            if save_or_error("Attendance could not be saved. It may already exist."):
                flash(f"Attendance marked for {student.name}.", "success")
                return redirect(url_for("main.index"))
        except ValueError as exc:
            flash(str(exc), "danger")
    return render_template("kiosk.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.query(User).filter_by(email=email).first()
        if user and user.active and user.role == "admin" and check_password_hash(user.password_hash, password):
            login_user(user)
            audit("login", "Signed in")
            db.session.commit()
            return redirect(url_for("main.dashboard"))
        flash("Invalid credentials or inactive account.", "danger")
    return render_template("login.html")


@bp.post("/logout")
@login_required
def logout():
    audit("logout", "Signed out")
    db.session.commit()
    logout_user()
    return redirect(url_for("main.login"))


@bp.route("/dashboard")
@roles("admin")
def dashboard():
    today = local_now().date()
    stats = {
        "users": db.session.query(User).filter_by(active=True, role="employee").count(),
        "today": db.session.query(Attendance).filter_by(date=today).count(),
        "locations": db.session.query(Location).filter_by(active=True).count(),
    }
    recent = allowed_attendance().order_by(Attendance.date.desc(), Attendance.id.desc()).limit(6).all()
    return render_template("dashboard.html", stats=stats, recent=recent, today=today)


def allowed_attendance():
    return db.session.query(Attendance).join(User, Attendance.user_id == User.id)


@bp.route("/history")
@roles("admin")
def history():
    q = allowed_attendance()
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    try:
        if start:
            q = q.filter(Attendance.date >= date.fromisoformat(start))
        if end:
            q = q.filter(Attendance.date <= date.fromisoformat(end))
    except ValueError:
        flash("Invalid date filter.", "danger")
    rows = q.order_by(Attendance.date.desc(), Attendance.id.desc()).limit(500).all()
    return render_template("history.html", rows=rows, start=start, end=end)


@bp.route("/reports")
@roles("admin")
def reports():
    q = allowed_attendance()
    month = request.args.get("month") or local_now().strftime("%Y-%m")
    try:
        first = date.fromisoformat(month + "-01")
    except ValueError:
        abort(400)
    if first.month == 12:
        next_month = date(first.year + 1, 1, 1)
    else:
        next_month = date(first.year, first.month + 1, 1)
    rows = q.filter(Attendance.date >= first, Attendance.date < next_month).order_by(Attendance.date.desc()).all()
    summary = {}
    for row in rows:
        key = (row.user.id, row.user.name)
        summary.setdefault(key, {"present": 0, "late": 0, "approved": 0})[row.status] += 1
    return render_template("reports.html", rows=rows, summary=summary, month=month)


@bp.route("/profile", methods=["GET", "POST"])
@roles("admin")
def profile():
    if request.method == "POST":
        old = request.form.get("old_password", "")
        new = request.form.get("new_password", "")
        if not check_password_hash(current_user.password_hash, old):
            flash("Current password is incorrect.", "danger")
        elif len(new) < 12:
            flash("New password must be at least 12 characters.", "danger")
        else:
            current_user.password_hash = generate_password_hash(new)
            audit("password", "Changed password")
            if save_or_error():
                flash("Password updated.", "success")
                return redirect(url_for("main.profile"))
    return render_template("profile.html")


@bp.route("/admin/users", methods=["GET", "POST"])
@roles("admin")
def users():
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            if not name or len(name) > 120:
                raise ValueError("Enter a student name of up to 120 characters.")
            location_id = int(request.form["location_id"]) if request.form.get("location_id") else None
            validate_assignment("employee", None, location_id)
            photos = json.loads(request.form.get("photos", "[]"))
            if not isinstance(photos, list) or len(photos) != 3:
                raise ValueError("Capture all 3 face photos while registering the student.")
            faces = [extract_face(photo) for photo in photos]
            existing = db.session.query(FaceIdentity).join(User, FaceIdentity.user_id == User.id).filter(User.active.is_(True), User.role == "employee").all()
            if any(match_registered_face(existing, face) for face in faces):
                raise ValueError("This face is already registered.")
            user = User(name=name, email=f"student-{uuid4().hex}@attendix.invalid", password_hash=generate_password_hash(secrets.token_urlsafe(32)), role="employee", department=request.form.get("department", "").strip()[:120], location_id=location_id)
            db.session.add(user)
            db.session.flush()
            db.session.add(FaceIdentity(user_id=user.id, face_data=serialize_faces(faces)))
            audit("student_create", f"Registered student #{user.id} with face reference")
            if save_or_error("Could not register student. Try again."):
                flash(f"{name} registered with face and location.", "success")
                return redirect(url_for("main.users"))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    students = db.session.query(User).filter_by(role="employee").order_by(User.name).all()
    return render_template("users.html", users=students, locations=db.session.query(Location).filter_by(active=True).all())


def validate_assignment(role, manager_id, location_id):
    if manager_id:
        manager = db.session.get(User, manager_id)
        if not manager or not manager.active or manager.role not in {"manager", "admin"}:
            raise ValueError("Invalid manager")
    if location_id:
        location = db.session.get(Location, location_id)
        if not location or not location.active:
            raise ValueError("Invalid location")
    if role == "employee" and not location_id:
        raise ValueError("Employee needs a location")


@bp.route("/admin/users/<int:user_id>", methods=["GET", "POST"])
@roles("admin")
def edit_user(user_id):
    user = db.session.get(User, user_id)
    if not user or user.role != "employee":
        abort(404)
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            if not name or len(name) > 120:
                raise ValueError("Enter a student name of up to 120 characters.")
            location_id = int(request.form["location_id"]) if request.form.get("location_id") else None
            validate_assignment("employee", None, location_id)
            user.name = name
            user.department = request.form.get("department", "").strip()[:120]
            user.location_id = location_id
            user.active = bool(request.form.get("active"))
            if request.form.get("photos"):
                photos = json.loads(request.form["photos"])
                if not isinstance(photos, list) or len(photos) != 3:
                    raise ValueError("Capture all 3 face photos to replace the reference.")
                image = serialize_faces([extract_face(photo) for photo in photos])
                identity = db.session.query(FaceIdentity).filter_by(user_id=user.id).first()
                if identity:
                    identity.face_data = image
                    identity.created_at = datetime.now(timezone.utc)
                else:
                    db.session.add(FaceIdentity(user_id=user.id, face_data=image))
            audit("student_update", f"Updated student #{user.id}")
            if save_or_error():
                flash("Student updated.", "success")
                return redirect(url_for("main.users"))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return render_template("edit_user.html", user=user, locations=db.session.query(Location).filter_by(active=True).all())


@bp.route("/admin/locations", methods=["GET", "POST"])
@roles("admin")
def locations():
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            lat, lon = validate_coordinates(request.form.get("latitude"), request.form.get("longitude"))
            radius = int(request.form.get("radius_m", "0"))
            if not name or not 20 <= radius <= 5000:
                raise ValueError("Enter a site name and radius from 20 to 5000 metres.")
            location = Location(name=name, latitude=lat, longitude=lon, radius_m=radius)
            db.session.add(location)
            db.session.flush()
            db.session.add(Schedule(location_id=location.id, start_time=time(9), end_time=time(18), grace_minutes=15, working_days="0,1,2,3,4"))
            audit("location_create", f"Created location {name}")
            if save_or_error():
                flash("Location created. Update its schedule if needed.", "success")
                return redirect(url_for("main.locations"))
        except ValueError as exc:
            flash(str(exc), "danger")
    rows = db.session.query(Location).order_by(Location.name).all()
    schedules = {s.location_id: s for s in db.session.query(Schedule).all()}
    return render_template("locations.html", rows=rows, schedules=schedules)


@bp.route("/admin/locations/<int:location_id>", methods=["GET", "POST"])
@roles("admin")
def edit_location(location_id):
    location = db.session.get(Location, location_id)
    if not location:
        abort(404)
    schedule = db.session.query(Schedule).filter_by(location_id=location_id).first()
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            lat, lon = validate_coordinates(request.form.get("latitude"), request.form.get("longitude"))
            radius = int(request.form.get("radius_m", "0"))
            start = time.fromisoformat(request.form.get("start_time", ""))
            end = time.fromisoformat(request.form.get("end_time", ""))
            grace = int(request.form.get("grace_minutes", "-1"))
            days = request.form.getlist("working_days")
            if not name or not 20 <= radius <= 5000 or end <= start or not 0 <= grace <= 120 or not days or any(d not in {str(i) for i in range(7)} for d in days):
                raise ValueError("Check name, radius, time, grace period and working days.")
            location.name, location.latitude, location.longitude, location.radius_m = name, lat, lon, radius
            location.active = bool(request.form.get("active"))
            if not schedule:
                schedule = Schedule(location_id=location_id)
                db.session.add(schedule)
            schedule.start_time, schedule.end_time, schedule.grace_minutes, schedule.working_days = start, end, grace, ",".join(sorted(set(days)))
            audit("location_update", f"Updated location #{location_id}")
            if save_or_error():
                flash("Location and schedule updated.", "success")
                return redirect(url_for("main.locations"))
        except ValueError as exc:
            flash(str(exc), "danger")
    return render_template("edit_location.html", location=location, schedule=schedule)
