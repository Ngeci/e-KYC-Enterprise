import secrets
import string
from functools import wraps

from flask import abort, current_app, g, redirect, request, session, url_for

from .extensions import db
from .models import AuditLog, Market, RolePermission, User

SPECIAL = "!@#$%^&*()_+-=[]{}|;:',.<>?/"


def password_problems(password):
    password = password or ""
    min_len = current_app.config["PASSWORD_MIN_LENGTH"]
    problems = []
    if len(password) < min_len:
        problems.append(f"at least {min_len} characters")
    if not any(c.isupper() for c in password):
        problems.append("an uppercase letter")
    if not any(c.islower() for c in password):
        problems.append("a lowercase letter")
    if not any(c.isdigit() for c in password):
        problems.append("a number")
    if not any(c in SPECIAL for c in password):
        problems.append("a special character")
    return problems


def generate_temp_password():
    alphabet = string.ascii_letters + string.digits + "!@#$%&*?"
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(14))
        if not password_problems(candidate):
            return candidate


def current_user():
    if hasattr(g, "_user"):
        return g._user
    user = None
    uid = session.get("uid")
    if uid:
        user = db.session.get(User, uid)
        if not user or not user.is_active:  # disabled accounts lose access immediately
            session.clear()
            user = None
    g._user = user
    return user


def safe_next(target):
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("main.dashboard")


def audit(action, target=None, detail=None, username=None):
    user = current_user()
    db.session.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else username,
            action=action,
            target=target,
            detail=(detail or "")[:500],
            ip=request.remote_addr,
        )
    )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for("auth.login", next=request.path))
        if user.must_change_password and request.endpoint not in ("auth.change_password", "auth.logout"):
            return redirect(url_for("auth.change_password"))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            user = current_user()
            if user.role not in roles:
                audit("access_denied", target=request.path, detail=f"role={user.role}")
                db.session.commit()
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def visible_markets(user):
    """Admins and staff see every active market; vendors only the ones assigned to them."""
    query = Market.query.filter_by(is_active=True).order_by(Market.name)
    if user.role == "vendor":
        query = query.filter(Market.users.any(User.id == user.id))
    return query.all()


# ---- module-level access (sidebar + route protection) ----
MODULES = [  # key, label, endpoint
    ("dashboard", "Dashboard", "main.dashboard"),
    ("executive", "Executive", "main.executive"),
    ("monetization", "Monetization", "main.monetization"),
    ("upgrade", "Upgrade", "main.upgrade"),
    ("operational", "Operational", "main.operational"),
    ("reports", "Reports", "main.reports"),
    ("data", "Data sources", "main.data_view"),
    ("notifications", "Notifications", "notify.inbox"),
    ("users", "User Management", "admin.users"),
    ("settings", "Settings", "main.settings"),
]
ADMIN_ONLY = {"users"}
DEFAULT_ACCESS = {
    "executive": {"dashboard", "executive", "monetization", "upgrade", "operational", "reports", "notifications", "settings"},
    "staff": {"dashboard", "operational", "upgrade", "reports", "data", "notifications", "settings"},
    "vendor": {"dashboard", "operational", "notifications", "settings"},
}


def allowed_modules(role):
    if role == "admin":
        return {key for key, _, _ in MODULES}
    if hasattr(g, "_modules") and g._modules[0] == role:
        return g._modules[1]
    allowed = set(DEFAULT_ACCESS.get(role, set()))
    for row in RolePermission.query.filter_by(role=role):
        (allowed.add if row.allowed else allowed.discard)(row.module)
    allowed -= ADMIN_ONLY
    g._modules = (role, allowed)
    return allowed


def module_required(name):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            user = current_user()
            if name not in allowed_modules(user.role):
                audit("access_denied", target=request.path, detail=f"module={name} role={user.role}")
                db.session.commit()
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator
