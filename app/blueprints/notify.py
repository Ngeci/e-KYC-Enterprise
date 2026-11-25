from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import ROLES, Notification
from ..security import audit, current_user, module_required, role_required
from ..services.notifications import mark_read, notify, unread_query, visible_query

bp = Blueprint("notify", __name__)


@bp.route("/")
@module_required("notifications")
def inbox():
    user = current_user()
    show = request.args.get("show", "all")
    query = unread_query(user) if show == "unread" else visible_query(user)
    rows = query.order_by(Notification.created_at.desc()).limit(200).all()
    read_ids = {n.id for n in rows if any(r.user_id == user.id for r in n.reads)}
    return render_template("notifications.html", rows=rows, read_ids=read_ids, show=show, roles=ROLES)


@bp.route("/<int:notification_id>/read", methods=["POST"])
@module_required("notifications")
def read_one(notification_id):
    user = current_user()
    if not visible_query(user).filter(Notification.id == notification_id).first():
        abort(404)
    mark_read(user, [notification_id])
    db.session.commit()
    return redirect(request.referrer or url_for("notify.inbox"))


@bp.route("/read-all", methods=["POST"])
@module_required("notifications")
def read_all():
    user = current_user()
    mark_read(user, [n.id for n in unread_query(user).all()])
    db.session.commit()
    return redirect(request.referrer or url_for("notify.inbox"))


@bp.route("/announce", methods=["POST"])
@role_required("admin")
def announce():
    title = (request.form.get("title") or "").strip()
    message = (request.form.get("message") or "").strip()
    audience = request.form.get("audience", "all")
    category = "alert" if request.form.get("category") == "alert" else "announcement"
    if not title or not message:
        flash("A title and a message are required.", "error")
    elif audience != "all" and audience not in ROLES:
        flash("Choose a valid audience.", "error")
    else:
        notify(title, message, category, role=None if audience == "all" else audience,
               created_by=current_user().username)
        audit("announcement", target=audience, detail=title[:200])
        db.session.commit()
        flash("Announcement sent.", "ok")
    return redirect(url_for("notify.inbox"))
