"""The only analytics module that touches the database. Everything else works on plain dicts."""
from datetime import timedelta

from sqlalchemy import func

from ..extensions import db
from ..models import DailyMetric, ExtraMetric, Market, StatusCount
from .calc import Scope


def load_scope(market_ids, days):
    scope = Scope(days=days)
    if not market_ids:
        return scope
    scope.latest = db.session.query(func.max(DailyMetric.report_date)) \
        .filter(DailyMetric.market_id.in_(market_ids)).scalar()
    if scope.latest is None:
        return scope
    scope.start = scope.latest - timedelta(days=days - 1) if days else None
    names = {m.id: m.name for m in Market.query.filter(Market.id.in_(market_ids))}

    def metric_rows(query):
        return [{"market": names.get(r.market_id, "?"), "date": r.report_date, "lite": r.lite, "premium": r.premium,
                 "not_registered": r.not_registered, "total": r.total_reported} for r in query.all()]

    base = DailyMetric.query.filter(DailyMetric.market_id.in_(market_ids))
    scope.metrics = metric_rows((base.filter(DailyMetric.report_date >= scope.start) if scope.start else base)
                                .order_by(DailyMetric.report_date))
    if scope.start:
        scope.prev_metrics = metric_rows(base.filter(DailyMetric.report_date < scope.start,
                                                     DailyMetric.report_date >= scope.start - timedelta(days=days)))

    sq = StatusCount.query.filter(StatusCount.market_id.in_(market_ids))
    eq = ExtraMetric.query.filter(ExtraMetric.market_id.in_(market_ids))
    if scope.start:
        sq = sq.filter(StatusCount.report_date >= scope.start)
        eq = eq.filter(ExtraMetric.report_date >= scope.start)
    scope.status = [{"market": names.get(r.market_id, "?"), "date": r.report_date, "code": r.status_code,
                     "label": r.status_label, "count": r.count} for r in sq.all()]
    scope.extras = [{"market": names.get(r.market_id, "?"), "date": r.report_date, "metric": r.metric,
                     "dimension": r.dimension, "value": r.value} for r in eq.all()]
    return scope
