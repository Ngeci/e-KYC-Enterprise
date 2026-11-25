import re
import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from ..extensions import db
from ..models import ROLES, AuditLog, Market, RolePermission, User, utcnow
from ..security import (ADMIN_ONLY, DEFAULT_ACCESS, MODULES, allowed_modules, audit, current_user,
                        generate_temp_password, role_required)
from ..services.notifications import notify

bp = Blueprint("admin", __name__)
USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,50}$")


def _markets_from_form():
    return Market.query.filter(Market.id.in_(request.form.getlist("markets", type=int))).all()


def _active_admins():
    return User.query.filter_by(role="admin", is_active=True, deleted_at=None).count()


@bp.route("/users")
@role_required("admin")
def users():
    return render_template("users.html", users=User.query.filter_by(deleted_at=None).order_by(User.username).all(),
                           markets=Market.query.order_by(Market.name).all(), roles=ROLES)


@bp.route("/users/create", methods=["POST"])
@role_required("admin")
def create_user():
    username = (request.form.get("username") or "").strip().lower()
    role = request.form.get("role")
    if not USERNAME_RE.match(username) or role not in ROLES:
        flash("Use 3-50 lowercase letters, digits, dots, dashes or underscores, and pick a role.", "error")
    elif User.query.filter_by(username=username).first():
        flash("That username already exists.", "error")
    else:
        temp = generate_temp_password()
        user = User(username=username, email=(request.form.get("email") or "").strip()[:190] or None,
                    role=role, must_change_password=True)
        user.set_password(temp)
        user.markets = _markets_from_form()
        db.session.add(user)
        db.session.flush()
        notify("Welcome to e-KYC Analytics", f"Your account was created with the {role} role. "
               "Open Settings to complete your profile.", "account", user_id=user.id, created_by=current_user().username)
        audit("user_created", target=username, detail=f"role={role}")
        db.session.commit()
        flash(f"User {username} created. One-time password (shown once): {temp}", "ok")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@role_required("admin")
def edit_user(user_id):
    user = db.session.get(User, user_id)
    if not user or user.deleted_at:
        abort(404)
    me = current_user()
    if request.method == "POST":
        role = request.form.get("role")
        email = (request.form.get("email") or "").strip()[:190]
        active = request.form.get("is_active") == "on"
        if role not in ROLES or (email and ("@" not in email or " " in email)):
            flash("Choose a valid role and email address.", "error")
        elif user.id == me.id and (role != "admin" or not active):
            flash("You cannot remove your own admin role or deactivate yourself.", "error")
        elif user.role == "admin" and (role != "admin" or not active) and _active_admins() <= 1:
            flash("At least one active administrator must remain.", "error")
        else:
            changed_role = role != user.role
            user.email, user.role, user.is_active = email or None, role, active
            user.markets = _markets_from_form()
            if changed_role:
                notify("Your role was changed", f"An administrator changed your role to {role}.", "account", user_id=user.id,
                       created_by=me.username)
            audit("user_edited", target=user.username, detail=f"role={role} active={active}")
            db.session.commit()
            flash(f"{user.username} updated.", "ok")
            return redirect(url_for("admin.users"))
    return render_template("user_edit.html", u=user, roles=ROLES, markets=Market.query.order_by(Market.name).all(),
                           modules=sorted(allowed_modules(user.role)))


@bp.route("/users/<int:user_id>/<action>", methods=["POST"])
@role_required("admin")
def user_action(user_id, action):
    user = db.session.get(User, user_id)
    if not user or user.deleted_at:
        abort(404)
    me = current_user()
    if action == "disable":
        if user.id == me.id or (user.role == "admin" and _active_admins() <= 1):
            flash("You cannot deactivate this account.", "error")
            return redirect(url_for("admin.users"))
        user.is_active = False
    elif action == "enable":
        user.is_active = True
    elif action == "unlock":
        user.locked_until, user.failed_attempts = None, 0
    elif action == "reset":
        temp = generate_temp_password()
        user.set_password(temp)
        user.must_change_password = True
        notify("Password reset", "An administrator reset your password. You must choose a new one at your next sign-in.",
               "account", user_id=user.id, created_by=me.username)
        flash(f"Password reset for {user.username}. One-time password (shown once): {temp}", "ok")
    elif action == "force-change":
        user.must_change_password = True
        flash(f"{user.username} must change their password at next sign-in.", "ok")
    else:
        abort(404)
    audit(f"user_{action.replace('-', '_')}", target=user.username)
    db.session.commit()
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
@role_required("admin")
def delete_user(user_id):
    """Removes the person from the system but keeps their history: the account is anonymised, never row-deleted."""
    user = db.session.get(User, user_id)
    if not user or user.deleted_at:
        abort(404)
    if user.id == current_user().id or (user.role == "admin" and _active_admins() <= 1):
        flash("You cannot delete this account.", "error")
    elif (request.form.get("confirm") or "").strip().lower() != user.username:
        flash("Type the username exactly to confirm deletion.", "error")
    else:
        old = user.username
        user.username, user.email = f"deleted-{user.id}", None
        user.password_hash = generate_password_hash(secrets.token_hex(32))
        user.is_active, user.deleted_at = False, utcnow()
        user.markets = []
        audit("user_deleted", target=old, detail="account anonymised; history retained")
        db.session.commit()
        flash(f"{old} was deleted. Their audit history is kept for compliance.", "ok")
    return redirect(url_for("admin.users"))


@bp.route("/permissions", methods=["GET", "POST"])
@role_required("admin")
def permissions():
    grantable = [(k, label) for k, label, _ in MODULES if k not in ADMIN_ONLY]
    roles = [r for r in ROLES if r != "admin"]
    if request.method == "POST":
        existing = {(p.role, p.module): p for p in RolePermission.query.all()}
        for role in roles:
            for key, _ in grantable:
                wanted = request.form.get(f"{role}:{key}") == "on"
                row = existing.get((role, key)) or RolePermission(role=role, module=key)
                row.allowed = wanted
                db.session.add(row)
        audit("permissions_updated")
        db.session.commit()
        flash("Access permissions saved. They apply from each user's next page load.", "ok")
        return redirect(url_for("admin.permissions"))
    matrix = {role: allowed_modules(role) for role in roles}
    return render_template("permissions.html", grantable=grantable, roles=roles, matrix=matrix, defaults=DEFAULT_ACCESS)


@bp.route("/markets", methods=["POST"])
@role_required("admin")
def add_market():
    code = (request.form.get("code") or "").strip().upper()
    name = (request.form.get("name") or "").strip()
    if not re.match(r"^[A-Z0-9]{2,10}$", code) or not name:
        flash("Market code must be 2-10 letters/digits and a name is required.", "error")
    elif Market.query.filter_by(code=code).first():
        flash("That market code already exists.", "error")
    else:
        db.session.add(Market(code=code, name=name[:120], country=(request.form.get("country") or "")[:80] or None))
        audit("market_created", target=code)
        db.session.commit()
        flash(f"Market {name} added.", "ok")
    return redirect(url_for("admin.users"))


@bp.route("/audit")
@role_required("admin")
def audit_log():
    rows = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(300).all()
    return render_template("audit.html", rows=rows)
