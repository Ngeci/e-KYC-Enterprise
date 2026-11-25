from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db

ROLES = ("admin", "executive", "staff", "vendor")


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


user_markets = db.Table(
    "user_markets",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("market_id", db.Integer, db.ForeignKey("markets.id"), primary_key=True),
)


class Market(db.Model):
    __tablename__ = "markets"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    country = db.Column(db.String(80))
    is_active = db.Column(db.Boolean, default=True, nullable=False)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(190))
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="vendor")
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    must_change_password = db.Column(db.Boolean, default=True, nullable=False)
    failed_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime)

    markets = db.relationship("Market", secondary=user_markets, backref="users")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_locked(self):
        return self.locked_until is not None and self.locked_until > utcnow()


class ImportBatch(db.Model):
    __tablename__ = "import_batches"

    id = db.Column(db.Integer, primary_key=True)
    market_id = db.Column(db.Integer, db.ForeignKey("markets.id"), nullable=False)
    filename = db.Column(db.String(255))
    sha256 = db.Column(db.String(64), index=True)
    uploaded_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    metric_rows = db.Column(db.Integer, default=0)
    status_rows = db.Column(db.Integer, default=0)
    issue_count = db.Column(db.Integer, default=0)

    market = db.relationship("Market")


class DailyMetric(db.Model):
    __tablename__ = "daily_metrics"
    __table_args__ = (db.UniqueConstraint("market_id", "report_date", name="uq_metric_market_date"),)

    id = db.Column(db.Integer, primary_key=True)
    market_id = db.Column(db.Integer, db.ForeignKey("markets.id"), nullable=False, index=True)
    report_date = db.Column(db.Date, nullable=False, index=True)
    lite = db.Column(db.Integer, default=0, nullable=False)
    premium = db.Column(db.Integer, default=0, nullable=False)
    not_registered = db.Column(db.Integer, default=0, nullable=False)
    total_reported = db.Column(db.Integer, default=0, nullable=False)
    batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"))

    @property
    def successful(self):
        return self.lite + self.premium


class StatusCount(db.Model):
    __tablename__ = "status_counts"
    __table_args__ = (
        db.UniqueConstraint("market_id", "report_date", "status_code", name="uq_status_market_date_code"),
    )

    id = db.Column(db.Integer, primary_key=True)
    market_id = db.Column(db.Integer, db.ForeignKey("markets.id"), nullable=False, index=True)
    report_date = db.Column(db.Date, nullable=False, index=True)
    status_code = db.Column(db.String(10), nullable=False)
    status_label = db.Column(db.String(120), nullable=False)
    count = db.Column(db.Integer, default=0, nullable=False)
    batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"))


class ValidationIssue(db.Model):
    __tablename__ = "validation_issues"
    __table_args__ = (db.UniqueConstraint("market_id", "report_date", "rule", name="uq_issue_market_date_rule"),)

    id = db.Column(db.Integer, primary_key=True)
    market_id = db.Column(db.Integer, db.ForeignKey("markets.id"), nullable=False, index=True)
    report_date = db.Column(db.Date, nullable=False, index=True)
    rule = db.Column(db.String(40), nullable=False)
    severity = db.Column(db.String(10), nullable=False)  # critical | warning | info
    message = db.Column(db.String(500), nullable=False)
    expected = db.Column(db.String(60))
    actual = db.Column(db.String(60))
    status = db.Column(db.String(15), default="open", nullable=False)  # open | acknowledged | resolved
    note = db.Column(db.String(500))
    batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_by = db.Column(db.String(100))
    updated_at = db.Column(db.DateTime)

    market = db.relationship("Market")


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)
    user_id = db.Column(db.Integer)
    username = db.Column(db.String(100))
    action = db.Column(db.String(60), nullable=False, index=True)
    target = db.Column(db.String(120))
    detail = db.Column(db.String(500))
    ip = db.Column(db.String(64))


class RolePermission(db.Model):
    """Per-role module overrides. Absent rows fall back to the defaults in security.py."""
    __tablename__ = "role_permissions"
    __table_args__ = (db.UniqueConstraint("role", "module", name="uq_role_module"),)

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    module = db.Column(db.String(30), nullable=False)
    allowed = db.Column(db.Boolean, default=True, nullable=False)


class Notification(db.Model):
    """user_id set = personal. user_id empty = broadcast to `role` (or everyone when role is empty)."""
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    role = db.Column(db.String(20))
    category = db.Column(db.String(20), default="announcement", nullable=False)  # announcement | alert | account
    title = db.Column(db.String(160), nullable=False)
    message = db.Column(db.String(1000), nullable=False)
    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)

    reads = db.relationship("NotificationRead", backref="notification", cascade="all, delete-orphan")


class NotificationRead(db.Model):
    __tablename__ = "notification_reads"

    notification_id = db.Column(db.Integer, db.ForeignKey("notifications.id"), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    read_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class ExtraMetric(db.Model):
    """Business data the registration workbook cannot provide (costs, transactions, channels, ...)."""
    __tablename__ = "extra_metrics"
    __table_args__ = (db.UniqueConstraint("market_id", "report_date", "metric", "dimension", name="uq_extra"),)

    id = db.Column(db.Integer, primary_key=True)
    market_id = db.Column(db.Integer, db.ForeignKey("markets.id"), nullable=False, index=True)
    report_date = db.Column(db.Date, nullable=False, index=True)
    metric = db.Column(db.String(40), nullable=False)
    dimension = db.Column(db.String(80), default="", nullable=False)
    value = db.Column(db.Float, nullable=False)
    uploaded_by = db.Column(db.String(100))
