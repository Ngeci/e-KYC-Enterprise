import hashlib
import io

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for

from ..extensions import db
from ..models import DailyMetric, ExtraMetric, ImportBatch, Market, ValidationIssue, utcnow
from ..security import audit, current_user, module_required, role_required, visible_markets
from ..services import calc, exports
from ..services.extras import METRICS, TEMPLATE, parse_extras_csv
from ..services.importer import import_report
from ..services.loader import load_scope
from ..services.notifications import notify_roles
from ..services.parser import ParseError, parse_workbook
from ..services.validation import RULE_LABELS

bp = Blueprint("main", __name__)
DAY_CHOICES = (7, 14, 30, 90, 0)


def _scope_args():
    markets = visible_markets(current_user())
    allowed = {m.id for m in markets}
    market_id = request.args.get("market", type=int)
    if market_id is not None and market_id not in allowed:
        abort(403)
    days = request.args.get("days", default=30, type=int)
    grain = request.args.get("grain", "daily")
    return {"markets": markets, "market_id": market_id, "ids": [market_id] if market_id else sorted(allowed),
            "days": days if days in DAY_CHOICES else 30, "grain": grain if grain in calc.GRAINS else "daily"}


def _page(template, builder, **extra):
    a = _scope_args()
    scope = load_scope(a["ids"], a["days"])
    data = builder(scope) if scope.metrics else None
    return render_template(template, data=data, scope=scope, markets=a["markets"], market_id=a["market_id"],
                           days=a["days"], grain=a["grain"], day_choices=DAY_CHOICES, grains=calc.GRAINS,
                           grain_labels=calc.GRAIN_LABELS, **extra)


@bp.route("/")
@module_required("dashboard")
def dashboard():
    grain = request.args.get("grain", "daily")
    return _page("dashboard.html", lambda s: calc.overview(s, grain if grain in calc.GRAINS else "daily"))


@bp.route("/executive")
@module_required("executive")
def executive():
    return _page("executive.html", calc.executive)


@bp.route("/monetization")
@module_required("monetization")
def monetization():
    return _page("monetization.html", calc.monetization)


@bp.route("/upgrade")
@module_required("upgrade")
def upgrade():
    return _page("upgrade.html", calc.upgrade)


@bp.route("/operational")
@module_required("operational")
def operational():
    return _page("operational.html", calc.operational)


@bp.route("/drill/success")
@module_required("dashboard")
def drill_success():
    return _page("drill_success.html", calc.drill_success)


@bp.route("/drill/kyc")
@module_required("dashboard")
def drill_kyc():
    return _page("drill_kyc.html", lambda s: calc.kyc(s.status))


@bp.route("/reports")
@module_required("reports")
def reports():
    kind = request.args.get("kind", "registration")
    kind = kind if kind in calc.REPORT_KINDS else "registration"
    grain = request.args.get("grain", "daily")
    grain = grain if grain in calc.GRAINS else "daily"
    return _page("reports.html", lambda s: calc.report(s, kind, grain), kind=kind, kinds=calc.REPORT_KINDS, fmt=calc.fmt)


@bp.route("/reports/export.<fmt>")
@module_required("reports")
def export_report(fmt):
    if fmt not in ("xlsx", "pdf"):
        abort(404)
    a = _scope_args()
    kind = request.args.get("kind", "registration")
    if kind not in calc.REPORT_KINDS:
        abort(400)
    scope = load_scope(a["ids"], a["days"])
    if not scope.metrics:
        abort(404)
    rep = calc.report(scope, kind, a["grain"])
    names = ", ".join(m.name for m in a["markets"] if m.id in a["ids"]) or "all markets"
    window = f"{scope.start:%d %b %Y} - {scope.latest:%d %b %Y}" if scope.start else f"to {scope.latest:%d %b %Y}"
    subtitle = f"{names} | {window}"
    audit("report_export", target=f"{kind}/{a['grain']}", detail=fmt)
    db.session.commit()
    if fmt == "xlsx":
        return Response(exports.to_xlsx(rep, subtitle),
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename=ekyc_{kind}_{a['grain']}.xlsx"})
    return Response(exports.to_pdf(rep, subtitle), mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=ekyc_{kind}_{a['grain']}.pdf"})


# ---------- findings ----------
@bp.route("/findings")
@module_required("operational")
def issues():
    a = _scope_args()
    status = request.args.get("status", "open")
    severity = request.args.get("severity", "")
    query = ValidationIssue.query.filter(ValidationIssue.market_id.in_(a["ids"]))
    if status in ("open", "acknowledged", "resolved"):
        query = query.filter_by(status=status)
    if severity in ("critical", "warning", "info"):
        query = query.filter_by(severity=severity)
    rows = query.order_by(ValidationIssue.report_date.desc(), ValidationIssue.severity).limit(300).all()
    return render_template("issues.html", rows=rows, markets=a["markets"], market_id=a["market_id"],
                           status=status, severity=severity, rule_labels=RULE_LABELS)


@bp.route("/findings/<int:issue_id>", methods=["POST"])
@role_required("admin", "staff")
def update_issue(issue_id):
    issue = db.session.get(ValidationIssue, issue_id) or abort(404)
    if issue.market_id not in {m.id for m in visible_markets(current_user())}:
        abort(403)
    new_status = request.form.get("status")
    if new_status not in ("open", "acknowledged", "resolved"):
        abort(400)
    issue.status = new_status
    issue.note = (request.form.get("note") or "").strip()[:500] or issue.note
    issue.updated_by, issue.updated_at = current_user().username, utcnow()
    audit("issue_updated", target=f"issue:{issue.id}", detail=f"{issue.rule} {issue.report_date} -> {new_status}")
    db.session.commit()
    return redirect(request.referrer or url_for("main.issues"))


# ---------- data sources ----------
@bp.route("/data", methods=["GET", "POST"])
@module_required("data")
def data_view():
    markets = Market.query.filter_by(is_active=True).order_by(Market.name).all()
    if request.method == "POST":
        market = db.session.get(Market, request.form.get("market", type=int) or 0)
        upload = request.files.get("report")
        if not market or not market.is_active:
            flash("Choose a market.", "error")
        elif not upload or not upload.filename.lower().endswith(".xlsx"):
            flash("Upload an .xlsx health-check report.", "error")
        else:
            content = upload.read()
            try:
                parsed = parse_workbook(io.BytesIO(content))
            except ParseError as exc:
                flash(str(exc), "error")
            else:
                batch, found, duplicate = import_report(parsed, market, current_user().username,
                                                        upload.filename[:255], hashlib.sha256(content).hexdigest())
                critical = sum(1 for f in found if f.severity == "critical")
                audit("import", target=market.code,
                      detail=f"{upload.filename[:120]}: {batch.metric_rows} days, {len(found)} findings")
                notify_roles(("admin", "executive", "staff"),
                             f"{market.name}: report imported" + (" with critical findings" if critical else ""),
                             f"{batch.metric_rows} days imported by {current_user().username}. {len(found)} validation "
                             f"findings, {critical} critical. Review them under Operational > Validation findings.",
                             "alert" if critical else "announcement", created_by="system")
                db.session.commit()
                for warning in parsed.warnings:
                    flash(warning, "warn")
                if duplicate:
                    flash("This exact file was imported before. Data was refreshed, nothing was duplicated.", "warn")
                flash(f"Imported {batch.metric_rows} days for {market.name}; {len(found)} validation findings.", "ok")
                return redirect(url_for("main.issues", market=market.id))
    batches = ImportBatch.query.order_by(ImportBatch.created_at.desc()).limit(10).all()
    extra_counts = {}
    for row in db.session.query(ExtraMetric.metric, db.func.count(ExtraMetric.id)).group_by(ExtraMetric.metric):
        extra_counts[row[0]] = row[1]
    return render_template("data.html", markets=markets, batches=batches, extra_metrics=METRICS, extra_counts=extra_counts)


@bp.route("/data/extra", methods=["POST"])
@module_required("data")
def upload_extra():
    upload = request.files.get("extra")
    if not upload or not upload.filename.lower().endswith(".csv"):
        flash("Upload a .csv file.", "error")
        return redirect(url_for("main.data_view"))
    markets = {m.code: m for m in Market.query.filter_by(is_active=True)}
    rows, errors = parse_extras_csv(upload.read(), set(markets))
    if errors:
        for e in errors:
            flash(e, "error")
        flash("Nothing was imported. Fix the lines above and upload again.", "error")
        return redirect(url_for("main.data_view"))

    user = current_user().username
    existing = {(e.market_id, e.report_date, e.metric, e.dimension): e for e in ExtraMetric.query.filter(
        ExtraMetric.report_date.in_({r["date"] for r in rows}))}
    for r in rows:
        key = (markets[r["market"]].id, r["date"], r["metric"], r["dimension"])
        row = existing.get(key) or ExtraMetric(market_id=key[0], report_date=key[1], metric=key[2], dimension=key[3])
        row.value, row.uploaded_by = r["value"], user
        db.session.add(row)
    audit("extra_import", target=upload.filename[:100], detail=f"{len(rows)} rows")
    db.session.commit()
    flash(f"Imported {len(rows)} business-data rows.", "ok")
    return redirect(url_for("main.data_view"))


@bp.route("/data/template.csv")
@module_required("data")
def extra_template():
    return Response(TEMPLATE, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=business_data_template.csv"})


# ---------- settings ----------
@bp.route("/settings", methods=["GET", "POST"])
@module_required("settings")
def settings():
    user = current_user()
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()[:190]
        if email and ("@" not in email or " " in email):
            flash("Enter a valid email address.", "error")
        else:
            user.email = email or None
            audit("profile_updated")
            db.session.commit()
            flash("Profile saved.", "ok")
        return redirect(url_for("main.settings"))
    return render_template("settings.html")


@bp.route("/export/metrics.csv")
@module_required("reports")
def export_metrics():
    import csv
    a = _scope_args()
    rows = DailyMetric.query.filter(DailyMetric.market_id.in_(a["ids"])).order_by(DailyMetric.report_date, DailyMetric.market_id).all()
    codes = {m.id: m.code for m in Market.query.all()}
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["market", "date", "lite", "premium", "not_registered", "total_reported", "success_rate_pct"])
    for r in rows:
        rate = round((r.lite + r.premium) / r.total_reported * 100, 2) if r.total_reported else ""
        writer.writerow([codes.get(r.market_id), r.report_date.isoformat(), r.lite, r.premium, r.not_registered, r.total_reported, rate])
    audit("export", target="metrics.csv", detail=f"{len(rows)} rows")
    db.session.commit()
    return Response(buffer.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=ekyc_metrics.csv"})


@bp.route("/healthz")
def healthz():
    return {"status": "ok"}
