import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.exc import SQLAlchemyError

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(test_config=None):
    load_dotenv()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=3 * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
        APP_TIMEZONE=os.getenv("APP_TIMEZONE", "Asia/Kolkata"),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"] or not app.config["SQLALCHEMY_DATABASE_URI"]:
        raise RuntimeError("Set SECRET_KEY and DATABASE_URL in .env")
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    login_manager.login_view = "main.login"

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        user = db.session.get(User, int(user_id))
        return user if user and user.active and user.role == "admin" else None

    from .routes import bp
    app.register_blueprint(bp)

    @app.errorhandler(SQLAlchemyError)
    def database_error(_):
        db.session.rollback()
        from flask import render_template
        return render_template("error.html", title="Database unavailable", message="Your action was not saved. Please try again later."), 503

    @app.cli.command("init-db")
    def init_db():
        db.create_all()
        print("Database tables created.")

    @app.cli.command("create-admin")
    def create_admin():
        from werkzeug.security import generate_password_hash
        email = os.getenv("ADMIN_EMAIL", "").strip().lower()
        password = os.getenv("ADMIN_PASSWORD", "")
        if not email or len(password) < 12:
            raise RuntimeError("Set ADMIN_EMAIL and ADMIN_PASSWORD (at least 12 characters) first")
        if db.session.query(User).filter_by(email=email).first():
            raise RuntimeError("An account with this email already exists")
        db.session.add(User(name="Administrator", email=email, password_hash=generate_password_hash(password), role="admin"))
        db.session.commit()
        print("Administrator created.")

    return app

