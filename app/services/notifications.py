from sqlalchemy import and_, or_

from ..extensions import db
from ..models import Notification, NotificationRead


def notify(title, message, category="announcement", user_id=None, role=None, created_by=None):
    db.session.add(Notification(title=title[:160], message=message[:1000], category=category,
                                user_id=user_id, role=role, created_by=created_by))


def notify_roles(roles, title, message, category="alert", created_by=None):
    for role in roles:
        notify(title, message, category, role=role, created_by=created_by)


def visible_query(user):
    return Notification.query.filter(or_(
        Notification.user_id == user.id,
        and_(Notification.user_id.is_(None),
             Notification.created_at >= user.created_at,
             or_(Notification.role.is_(None), Notification.role == user.role))))


def unread_query(user):
    return visible_query(user).filter(~Notification.reads.any(NotificationRead.user_id == user.id))


def bell(user):
    """(unread_count, [(notification, is_read), ...]) for the topbar dropdown."""
    recent = visible_query(user).order_by(Notification.created_at.desc()).limit(5).all()
    read_ids = set()
    if recent:
        read_ids = {r.notification_id for r in NotificationRead.query.filter(
            NotificationRead.user_id == user.id, NotificationRead.notification_id.in_([n.id for n in recent]))}
    return unread_query(user).count(), [(n, n.id in read_ids) for n in recent]


def mark_read(user, notification_ids):
    already = {r.notification_id for r in NotificationRead.query.filter(
        NotificationRead.user_id == user.id, NotificationRead.notification_id.in_(notification_ids))}
    for nid in notification_ids:
        if nid not in already:
            db.session.add(NotificationRead(notification_id=nid, user_id=user.id))
