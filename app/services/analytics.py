from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func

from ..extensions import db
from ..models import DailyMetric, StatusCount, ValidationIssue
from .statuses import GROUP_LABELS, GROUP_ORDER, group_of
from .validation import RULE_LABELS


def _rate(rows):
    total = sum(r.total_reported for r in rows)
    return (sum(r.lite + r.premium for r in rows) / total) if total else None


def empty_dashboard():
    return {"has_data": False, "kpi": {}, "chart": {"labels": [], "applications": [], "registered": [], "rate": []},
            "outcomes": [], "friction": [], "ledger": {"dates": [], "rules": [], "cells": {}},
            "latest": None, "start": None}


def dashboard_data(market_ids, days):
    if not market_ids:
        return empty_dashboard()

    latest = db.session.query(func.max(DailyMetric.report_date)) \
        .filter(DailyMetric.market_id.in_(market_ids)).scalar()
    if latest is None:
        return empty_dashboard()

    start = latest - timedelta(days=days - 1) if days else None
    base = DailyMetric.query.filter(DailyMetric.market_id.in_(market_ids))
    rows = (base.filter(DailyMetric.report_date >= start) if start else base) \
        .order_by(DailyMetric.report_date).all()

    previous_rate = None
    if start:
        previous = base.filter(DailyMetric.report_date < start,
                               DailyMetric.report_date >= start - timedelta(days=days)).all()
        previous_rate = _rate(previous)

    daily = defaultdict(lambda: {"applications": 0, "registered": 0})
    for r in rows:
        daily[r.report_date]["applications"] += r.total_reported
        daily[r.report_date]["registered"] += r.lite + r.premium
    labels = sorted(daily)

    overall = _rate(rows)
    open_q = ValidationIssue.query.filter(ValidationIssue.market_id.in_(market_ids), ValidationIssue.status == "open")
    if start:
        open_q = open_q.filter(ValidationIssue.report_date >= start)
    open_issues = open_q.all()

    applications = sum(r.total_reported for r in rows)
    registered = sum(r.lite + r.premium for r in rows)

    kpi = {
        "applications": applications,
        "registered": registered,
        "not_registered": sum(r.not_registered for r in rows),
        "rate": overall,
        "rate_delta": (overall - previous_rate) * 100 if overall is not None and previous_rate is not None else None,
        "open_issues": len(open_issues),
        "critical": sum(1 for i in open_issues if i.severity == "critical"),
        "days": len(labels),
    }

    status_q = db.session.query(StatusCount.status_code, func.max(StatusCount.status_label),
                                func.sum(StatusCount.count)) \
        .filter(StatusCount.market_id.in_(market_ids))
    if start:
        status_q = status_q.filter(StatusCount.report_date >= start)
    status_rows = status_q.group_by(StatusCount.status_code).all()

    grand = sum(int(c) for _, _, c in status_rows) or 1
    group_totals = defaultdict(int)
    for code, _, count in status_rows:
        group_totals[group_of(code)] += int(count)
    outcomes = [{"key": g, "label": GROUP_LABELS[g], "count": group_totals[g], "pct": group_totals[g] / grand * 100}
                for g in GROUP_ORDER if group_totals.get(g)]
    friction = sorted(
        ({"code": code, "label": label, "count": int(count), "pct": int(count) / grand * 100}
         for code, label, count in status_rows if code != "30" and int(count) > 0),
        key=lambda x: -x["count"])[:6]

    ledger_dates = labels[-14:]
    cells = defaultdict(dict)
    for issue in open_issues:
        if issue.report_date in ledger_dates:
            cells[issue.rule][issue.report_date.isoformat()] = {"severity": issue.severity, "message": issue.message}

    return {
        "has_data": True,
        "kpi": kpi,
        "chart": {
            "labels": [d.isoformat() for d in labels],
            "applications": [daily[d]["applications"] for d in labels],
            "registered": [daily[d]["registered"] for d in labels],
            "rate": [round(daily[d]["registered"] / daily[d]["applications"] * 100, 1)
                     if daily[d]["applications"] else None for d in labels],
        },
        "outcomes": outcomes,
        "friction": friction,
        "ledger": {"dates": [d.isoformat() for d in ledger_dates],
                   "rules": [(k, RULE_LABELS[k]) for k in RULE_LABELS if k != "MISSING_STATUS_DATA"],
                   "cells": cells},
        "latest": latest,
        "start": start,
    }
