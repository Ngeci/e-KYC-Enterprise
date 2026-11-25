import logging

from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import get_config
from .extensions import csrf, db, migrate


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or get_config())
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY is not set. Copy .env.example to .env and set it.")
    if app.config.get("TRUST_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    from .blueprints import admin, auth, main, notify
    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(admin.bp, url_prefix="/admin")
    app.register_blueprint(notify.bp, url_prefix="/notifications")

    from .filters import register_filters
    register_filters(app)
    from .cli import register_cli
    register_cli(app)

    @app.context_processor
    def inject_user():
        from .security import MODULES, allowed_modules, current_user
        from .services.notifications import bell
        user = current_user()
        if not user:
            return {"current_user": None}
        unread, recent = bell(user)
        allowed = allowed_modules(user.role)
        return {"current_user": user, "nav": [m for m in MODULES if m[0] in allowed],
                "unread_count": unread, "recent_notifications": recent}

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; "
            "form-action 'self'; base-uri 'self'")
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    for code, title in ((403, "Access denied"), (404, "Page not found"), (413, "File too large"),
                        (500, "Something went wrong")):
        app.register_error_handler(
            code, lambda e, code=code, title=title: (render_template("error.html", code=code, title=title), code))

    return app
