from datetime import timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import User, utcnow
from ..security import audit, current_user, login_required, password_problems, safe_next

bp = Blueprint("auth", __name__)
_DUMMY_HASH = generate_password_hash("not-a-real-password")  # equalises timing for unknown usernames


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        cfg = current_app.config
        user = User.query.filter_by(username=username).first()

        if user and user.is_locked():
            audit("login_blocked_locked", target=username, username=username)
            db.session.commit()
            flash("Too many failed attempts. Please try again later or contact an administrator.", "error")
        elif user and user.is_active and user.check_password(password):
            user.failed_attempts, user.locked_until, user.last_login_at = 0, None, utcnow()
            session.clear()  # new session on login prevents fixation
            session["uid"] = user.id
            session.permanent = True
            audit("login", target=username, username=username)
            db.session.commit()
            return redirect(safe_next(request.args.get("next")))
        else:
            if user is None:
                check_password_hash(_DUMMY_HASH, password)
            else:
                user.failed_attempts += 1
                if user.failed_attempts >= cfg["MAX_FAILED_LOGINS"]:
                    user.locked_until = utcnow() + timedelta(minutes=cfg["LOCKOUT_MINUTES"])
                    user.failed_attempts = 0
            audit("login_failed", target=username, username=username)
            db.session.commit()
            flash("Invalid username or password.", "error")

    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    if current_user():
        audit("logout")
        db.session.commit()
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    user = current_user()
    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""

        if not user.check_password(current):
            flash("Your current password is incorrect.", "error")
        elif new != confirm:
            flash("The new passwords do not match.", "error")
        elif new == current:
            flash("Choose a password you have not used here before.", "error")
        elif password_problems(new):
            flash("Password needs: " + ", ".join(password_problems(new)) + ".", "error")
        else:
            user.set_password(new)
            user.must_change_password = False
            audit("password_changed")
            db.session.commit()
            flash("Password updated.", "ok")
            return redirect(url_for("main.dashboard"))
    return render_template("change_password.html")
