"""Persists a parsed report idempotently and records validation issues."""
from datetime import datetime

from ..extensions import db
from ..models import DailyMetric, ImportBatch, StatusCount, ValidationIssue, utcnow
from .validation import validate


def import_report(parsed, market, username, filename, digest):
    duplicate = ImportBatch.query.filter_by(market_id=market.id, sha256=digest).first() is not None

    batch = ImportBatch(market_id=market.id, filename=filename, sha256=digest, uploaded_by=username)
    db.session.add(batch)
    db.session.flush()

    dates = list(parsed.metrics)
    existing_metrics = {
        m.report_date: m
        for m in DailyMetric.query.filter(DailyMetric.market_id == market.id, DailyMetric.report_date.in_(dates))
    }
    for day, values in parsed.metrics.items():
        row = existing_metrics.get(day) or DailyMetric(market_id=market.id, report_date=day)
        row.lite, row.premium = values["lite"], values["premium"]
        row.not_registered, row.total_reported = values["not_registered"], values["total_reported"]
        row.batch_id = batch.id
        db.session.add(row)

    existing_status = {
        (s.report_date, s.status_code): s
        for s in StatusCount.query.filter(StatusCount.market_id == market.id, StatusCount.report_date.in_(dates))
    }
    status_rows = 0
    for day, codes in parsed.status_counts.items():
        for code, count in codes.items():
            row = existing_status.get((day, code)) or StatusCount(market_id=market.id, report_date=day, status_code=code)
            row.status_label = parsed.status_labels.get(code, code)
            row.count = count
            row.batch_id = batch.id
            db.session.add(row)
            status_rows += 1

    found = validate(parsed.metrics, parsed.status_counts, parsed.control_totals)
    _sync_issues(market.id, dates, found, batch.id)

    batch.metric_rows = len(parsed.metrics)
    batch.status_rows = status_rows
    batch.issue_count = len(found)
    db.session.flush()
    return batch, found, duplicate


def _sync_issues(market_id, dates, found, batch_id):
    current = {
        (i.report_date, i.rule): i
        for i in ValidationIssue.query.filter(ValidationIssue.market_id == market_id,
                                              ValidationIssue.report_date.in_(dates))
    }
    seen = set()
    for item in found:
        key = (item.report_date, item.rule)
        seen.add(key)
        row = current.get(key)
        if row is None:
            db.session.add(ValidationIssue(
                market_id=market_id, report_date=item.report_date, rule=item.rule, severity=item.severity,
                message=item.message, expected=item.expected, actual=item.actual, batch_id=batch_id))
        elif row.status == "open":  # keep human decisions (acknowledged/resolved) intact
            row.message, row.severity = item.message, item.severity
            row.expected, row.actual, row.batch_id = item.expected, item.actual, batch_id

    for key, row in current.items():  # corrected source data clears the finding
        if key not in seen and row.status == "open":
            row.status = "resolved"
            row.note = "Cleared automatically by a later import."
            row.updated_by = "system"
            row.updated_at = utcnow()
