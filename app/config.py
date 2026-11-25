from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///ekyc.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.environ.get("SESSION_MINUTES", "30")))

    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB upload cap
    WTF_CSRF_TIME_LIMIT = None

    MAX_FAILED_LOGINS = 5
    LOCKOUT_MINUTES = 15
    PASSWORD_MIN_LENGTH = 10
    TRUST_PROXY = os.environ.get("TRUST_PROXY", "0") == "1"


class DevConfig(Config):
    DEBUG = True
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-not-for-production"
    SESSION_COOKIE_SECURE = False


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False


def get_config():
    env = os.environ.get("APP_ENV", "production").lower()
    return {"development": DevConfig, "testing": TestConfig}.get(env, Config)
