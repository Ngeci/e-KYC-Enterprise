"""Pure analytics. Takes plain dicts (see loader.py) and returns plain dicts. No Flask, no database."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from .statuses import GROUP_LABELS, GROUP_ORDER, group_of

GRAINS = ("daily", "weekly", "monthly", "yearly")
GRAIN_LABELS = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "yearly": "Yearly"}
ERROR_GROUPS = ("verification_error", "rejected")


@dataclass
class Scope:
    metrics: list = field(default_factory=list)       # market, date, lite, premium, not_registered, total
    prev_metrics: list = field(default_factory=list)  # same shape, the period before
    status: list = field(default_factory=list)        # market, date, code, label, count
    extras: list = field(default_factory=list)        # market, date, metric, dimension, value
    days: int = 30
    latest: object = None
    start: object = None


# ---------- basics ----------
def pct(n, d):
    return n / d if d else None


def bucket_key(d, grain):
    if grain == "weekly":
        return d - timedelta(days=d.weekday())
    if grain == "monthly":
        return d.replace(day=1)
    if grain == "yearly":
        return d.replace(month=1, day=1)
    return d


def bucket_label(k, grain):
    return {"weekly": "Wk " + k.strftime("%d %b"), "monthly": k.strftime("%b %Y"),
            "yearly": str(k.year)}.get(grain, k.strftime("%d %b"))


def totals(rows):
    t = {"lite": 0, "premium": 0, "not_registered": 0, "total": 0}
    for r in rows:
        for key in t:
            t[key] += r[key]
    t["registered"] = t["lite"] + t["premium"]
    t["rate"] = pct(t["registered"], t["total"])
    return t


def series(metrics, grain):
    buckets = defaultdict(list)
    for r in metrics:
        buckets[bucket_key(r["date"], grain)].append(r)
    out, prev = [], None
    for key in sorted(buckets):
        t = totals(buckets[key])
        t.update(key=key, label=bucket_label(key, grain), days=len({r["date"] for r in buckets[key]}))
        t["growth"] = (t["total"] - prev["total"]) / prev["total"] * 100 if prev and prev["total"] else None
        out.append(t)
        prev = t
    return out


def status_summary(status):
    codes, groups = {}, defaultdict(int)
    for s in status:
        entry = codes.setdefault(s["code"], [s["label"], 0])
        entry[1] += s["count"]
        groups[group_of(s["code"])] += s["count"]
    return codes, groups


def kyc(status):
    codes, groups = status_summary(status)
    if not codes:
        return None
    passed = groups["accepted"]
    failed = groups["verification_error"] + groups["rejected"]
    outstanding = groups["pending"] + groups["operator_edited"]
    abandoned = groups["abandoned"]
    attempts = passed + failed + outstanding
    everything = attempts + abandoned + groups.get("other", 0)

    def listing(*names):
        return sorted(((c, l, n) for c, (l, n) in codes.items() if group_of(c) in names and n),
                      key=lambda x: -x[2])

    return {
        "attempts": attempts, "passed": passed, "failed": failed, "outstanding": outstanding,
        "abandoned": abandoned, "applications": everything,
        "pass_rate": pct(passed, attempts), "fail_rate": pct(failed, attempts),
        "compliance_rate": pct(passed, passed + failed),
        "completion_rate": pct(everything - abandoned, everything), "dropoff_rate": pct(abandoned, everything),
        "breakdown": {"Passed": listing("accepted"), "Failed verification": listing(*ERROR_GROUPS),
                      "Outstanding": listing("pending", "operator_edited"), "Not finished": listing("abandoned")},
    }


def top_errors(status, n=5):
    codes, _ = status_summary(status)
    rows = [{"code": c, "label": l, "count": cnt} for c, (l, cnt) in codes.items()
            if group_of(c) in ERROR_GROUPS and cnt > 0]
    total = sum(r["count"] for r in rows) or 1
    for r in rows:
        r["share"] = r["count"] / total
    return sorted(rows, key=lambda r: -r["count"])[:n]


def errors_by_date(status):
    out = defaultdict(int)
    for s in status:
        if group_of(s["code"]) == "verification_error":
            out[s["date"]] += s["count"]
    return out


def growth_info(metrics):
    daily = {}
    for r in metrics:
        daily[r["date"]] = daily.get(r["date"], 0) + r["total"]
    dates = sorted(daily)
    if len(dates) >= 14:
        cur = sum(daily[d] for d in dates[-7:])
        prev = sum(daily[d] for d in dates[-14:-7])
        basis, mode = "last 7 days vs the 7 days before", "week"
    elif len(dates) >= 2:
        cur, prev = daily[dates[-1]], daily[dates[-2]]
        basis, mode = f"{dates[-1].strftime('%d %b')} vs {dates[-2].strftime('%d %b')}", "day"
    else:
        return None
    return {"rate": (cur - prev) / prev * 100 if prev else None, "current": cur, "previous": prev, "basis": basis,
            "mode": mode, "latest": dates[-1], "before": dates[-2]}


# ---------- extra (optional) business data ----------
def ex_sum(extras, metric):
    vals = [e["value"] for e in extras if e["metric"] == metric]
    return sum(vals) if vals else None


def ex_mean(extras, metric):
    vals = [e["value"] for e in extras if e["metric"] == metric]
    return sum(vals) / len(vals) if vals else None


def ex_by_dim(extras, metric):
    out = defaultdict(float)
    for e in extras:
        if e["metric"] == metric:
            out[e["dimension"]] += e["value"]
    return dict(out)


# ---------- chart specs (rendered by static/js/charts.js) ----------
def ds(label, data, color, kind=None, axis="y"):
    return {"label": label, "data": data, "color": color, "kind": kind, "axis": axis}


def spec(kind, labels, datasets, stacked=False, y="", y2=None):
    return {"type": kind, "labels": labels, "datasets": datasets, "stacked": stacked, "yTitle": y, "y2Title": y2}


def _round(values, nd=1):
    return [None if v is None else round(v, nd) for v in values]


# ---------- pages ----------
def overview(scope, grain="daily"):
    m = scope.metrics
    if not m:
        return None
    t = totals(m)
    ser = series(m, grain)
    codes, groups = status_summary(scope.status)
    k = kyc(scope.status)
    monthly, yearly = series(m, "monthly"), series(m, "yearly")
    days = len({r["date"] for r in m})
    labels = [b["label"] for b in ser]
    err_rows = top_errors(scope.status, 8)

    kpi = {
        "total": t["total"], "registered": t["registered"], "failed": t["not_registered"], "rate": t["rate"],
        "lite": t["lite"], "premium": t["premium"], "errors": groups.get("verification_error", 0) if codes else None,
        "growth": ser[-1]["growth"] if len(ser) > 1 else None,
        "growth_basis": f"{ser[-1]['label']} vs {ser[-2]['label']}" if len(ser) > 1 else None,
        "avg_daily": t["total"] / days, "avg_monthly": sum(b["total"] for b in monthly) / len(monthly),
        "avg_yearly": sum(b["total"] for b in yearly) / len(yearly), "days": days,
        "kyc_pass": k["pass_rate"] if k else None, "completion": k["completion_rate"] if k else None,
    }
    charts = {
        "growth": spec("bar", labels, [ds("Registrations", [b["total"] for b in ser], "grey"),
                                       ds("Growth vs previous (%)", _round([b["growth"] for b in ser]), "green", "line", "y1")],
                       y="Registrations", y2="Growth (%)"),
        "successFail": spec("bar", labels, [ds("Successful", [b["registered"] for b in ser], "green"),
                                            ds("Unsuccessful", [b["not_registered"] for b in ser], "ink")], stacked=True),
        "premiumLite": spec("bar", labels, [ds("Premium", [b["premium"] for b in ser], "green"),
                                            ds("Lite", [b["lite"] for b in ser], "mint")], stacked=True),
        "trend": spec("line", labels, [ds("Registrations", [b["total"] for b in ser], "ink"),
                                       ds("Successful", [b["registered"] for b in ser], "green")]),
        "errors": spec("doughnut", [e["label"] for e in err_rows], [ds("Errors", [e["count"] for e in err_rows], None)]),
    }
    return {"kpi": kpi, "charts": charts, "grain": grain, "has_status": bool(codes)}


def executive(scope):
    m = scope.metrics
    if not m:
        return None
    t = totals(m)
    k = kyc(scope.status)
    gi = growth_info(m)
    prev = totals(scope.prev_metrics) if scope.prev_metrics else None
    monthly, yearly = series(m, "monthly"), series(m, "yearly")
    daily = series(m, "daily")
    err_by_day = errors_by_date(scope.status)

    last5 = [dict(b, errors=err_by_day.get(b["key"]) if scope.status else None) for b in daily[-5:]]
    cost = ex_sum(scope.extras, "acquisition_cost")
    markets = defaultdict(list)
    for r in m:
        markets[r["market"]].append(r)
    market_rows = sorted(({"market": name, **totals(rows)} for name, rows in markets.items()),
                         key=lambda r: -r["total"])

    delta = (t["rate"] - prev["rate"]) * 100 if prev and prev["rate"] is not None and t["rate"] is not None else None
    first, last = min(r["date"] for r in m), max(r["date"] for r in m)
    lines = [f"From {first.strftime('%d %b %Y')} to {last.strftime('%d %b %Y')}, {t['total']:,} applications were received "
             f"and {t['registered']:,} ({t['rate'] * 100:.1f}%) ended in a registered customer."
             if t["rate"] is not None else f"{t['total']:,} applications were received."]
    if delta is not None:
        lines.append(f"The success rate is {abs(delta):.1f} points {'above' if delta >= 0 else 'below'} the previous period.")
    if gi and gi["rate"] is not None:
        if gi["mode"] == "week":
            lines.append(f"Application volume {'grew' if gi['rate'] >= 0 else 'fell'} {abs(gi['rate']):.1f}% ({gi['basis']}).")
        else:
            lines.append(f"Volume on {gi['latest']:%d %b} was {abs(gi['rate']):.1f}% {'higher' if gi['rate'] >= 0 else 'lower'} "
                         f"than on {gi['before']:%d %b}; with under two weeks of data this is a day-on-day swing, not a trend.")
    best = max(daily, key=lambda b: b["rate"] if b["rate"] is not None else -1)
    worst = min(daily, key=lambda b: b["rate"] if b["rate"] is not None else 2)
    if len(daily) > 1 and best["rate"] is not None:
        lines.append(f"Best day: {best['label']} ({best['rate'] * 100:.1f}%). Weakest day: {worst['label']} ({worst['rate'] * 100:.1f}%).")
    if k and k["pass_rate"] is not None:
        lines.append(f"KYC pass rate is {k['pass_rate'] * 100:.1f}%; {k['outstanding']:,} cases are still awaiting a decision.")

    sat = ex_mean(scope.extras, "satisfaction_score")
    return {
        "kpi": {
            "total": t["total"], "growth": gi["rate"] if gi else None, "growth_basis": gi["basis"] if gi else None,
            "rate": t["rate"], "rate_delta": delta, "failed": t["not_registered"],
            "avg_monthly": sum(b["total"] for b in monthly) / len(monthly),
            "avg_yearly": sum(b["total"] for b in yearly) / len(yearly),
            "months": len(monthly), "years": len(yearly),
            "cac": cost / t["registered"] if cost is not None and t["registered"] else None,
            "kyc_pass": k["pass_rate"] if k else None, "kyc_compliance": k["compliance_rate"] if k else None,
            "satisfaction": sat, "ratio": pct(t["premium"], t["lite"]),
        },
        "last5": last5, "monthly": monthly, "yearly": yearly, "markets": market_rows,
        "top_errors": top_errors(scope.status), "summary": lines,
        "comparisons": [
            {"label": "Latest period", "value": gi["current"] if gi else None, "prev": gi["previous"] if gi else None,
             "basis": gi["basis"] if gi else None},
            {"label": "Selected period vs previous", "value": t["total"], "prev": prev["total"] if prev else None,
             "basis": f"previous {scope.days} days" if prev else None},
        ],
        "charts": {"last5": spec("bar", [b["label"] for b in last5], [
            ds("Successful", [b["registered"] for b in last5], "green"),
            ds("Unsuccessful", [b["not_registered"] for b in last5], "ink")], stacked=True)},
    }


def operational(scope):
    m = scope.metrics
    if not m:
        return None
    t = totals(m)
    k = kyc(scope.status)
    top = top_errors(scope.status)
    codes, groups = status_summary(scope.status)
    dates = sorted({s["date"] for s in scope.status})[-5:]
    colors = ["green", "ink", "amber", "red", "grey"]
    per_code = defaultdict(lambda: defaultdict(int))
    for s in scope.status:
        per_code[s["code"]][s["date"]] += s["count"]
    stages = ex_by_dim(scope.extras, "stage_dropoff")
    channels = ex_by_dim(scope.extras, "channel_registrations")
    stage_total, channel_total = sum(stages.values()) or 1, sum(channels.values()) or 1
    return {
        "kpi": {"total": t["total"], "registered": t["registered"], "failed": t["not_registered"],
                "completion": k["completion_rate"] if k else None, "dropoff": k["dropoff_rate"] if k else None,
                "errors": groups.get("verification_error", 0) if codes else None,
                "kyc_pass": k["pass_rate"] if k else None},
        "top_errors": top,
        "stages": sorted(({"name": n, "count": c, "share": c / stage_total} for n, c in stages.items()),
                         key=lambda r: -r["count"]) or None,
        "channels": sorted(({"name": n, "count": c, "share": c / channel_total} for n, c in channels.items()),
                           key=lambda r: -r["count"]) or None,
        "outcomes": [{"label": GROUP_LABELS[g], "key": g, "count": groups[g]} for g in GROUP_ORDER if groups.get(g)],
        "charts": {
            "errorTrend": spec("line", [d.strftime("%d %b") for d in dates], [
                ds(e["label"], [per_code[e["code"]].get(d, 0) for d in dates], colors[i % 5]) for i, e in enumerate(top)]),
            "errorDist": spec("doughnut", [e["label"] for e in top], [ds("Errors", [e["count"] for e in top], None)]),
            "channels": spec("bar", [c for c in channels], [ds("Registrations", list(channels.values()), "green")]),
            "stages": spec("bar", [s for s in stages], [ds("Dropped here", list(stages.values()), "ink")]),
        },
        "last5_dates": [d.strftime("%d %b") for d in dates],
    }


def monetization(scope):
    m = scope.metrics
    if not m:
        return None
    t = totals(m)
    daily = series(m, "daily")
    cumulative, running = [], 0
    for b in daily:
        running += b["registered"]
        cumulative.append(running)

    products = defaultdict(dict)
    for e in scope.extras:
        if e["metric"] == "product_customers":
            products[e["dimension"]][e["date"]] = products[e["dimension"]].get(e["date"], 0) + e["value"]
    latest_prod = {p: v[max(v)] for p, v in products.items()}
    prod_dates = sorted({d for v in products.values() for d in v})
    colors = ["green", "ink", "amber", "grey", "mint", "red"]
    tx = ex_sum(scope.extras, "transactions")
    cost = ex_sum(scope.extras, "acquisition_cost")
    return {
        "kpi": {"lite": t["lite"], "premium": t["premium"], "ratio": pct(t["premium"], t["lite"]),
                "customers": t["registered"], "cac": cost / t["registered"] if cost is not None and t["registered"] else None,
                "avg_tx": tx / t["registered"] if tx is not None and t["registered"] else None,
                "favourite": max(latest_prod, key=latest_prod.get) if latest_prod else None,
                "premium_share": pct(t["premium"], t["registered"])},
        "products": sorted(latest_prod.items(), key=lambda x: -x[1]),
        "charts": {
            "customerGrowth": spec("line", [b["label"] for b in daily], [ds("Cumulative registered customers", cumulative, "green")]),
            "distribution": spec("doughnut", ["Premium", "Lite"], [ds("Accounts", [t["premium"], t["lite"]], None)]),
            "overTime": spec("bar", [b["label"] for b in daily], [ds("Premium", [b["premium"] for b in daily], "green"),
                                                                  ds("Lite", [b["lite"] for b in daily], "mint")], stacked=True),
            "adoption": spec("line", [d.strftime("%d %b") for d in prod_dates], [
                ds(p, [v.get(d) for d in prod_dates], colors[i % 6]) for i, (p, v) in enumerate(products.items())]),
        },
    }


def upgrade(scope):
    m = scope.metrics
    if not m:
        return None
    t = totals(m)
    daily = series(m, "daily")
    codes, groups = status_summary(scope.status)
    pipeline = [(c, codes[c][0], codes[c][1]) for c in ("10", "11", "60") if c in codes]
    g2_by_date = defaultdict(int)
    approved_by_date = defaultdict(int)
    for s in scope.status:
        if s["code"] == "60":
            g2_by_date[s["date"]] += s["count"]
        if s["code"] == "30":
            approved_by_date[s["date"]] += s["count"]
    dates = [b["key"] for b in daily]
    return {
        "kpi": {"lite": t["lite"], "premium": t["premium"], "ratio": pct(t["premium"], t["lite"]),
                "share": pct(t["premium"], t["registered"]),
                "waiting": sum(c for _, _, c in pipeline) if pipeline else None},
        "pipeline": pipeline,
        "charts": {
            "share": spec("line", [b["label"] for b in daily], [
                ds("Premium share of registrations (%)", _round([pct(b["premium"], b["registered"]) * 100
                                                                  if b["registered"] else None for b in daily]), "green")]),
            "backlog": spec("bar", [b["label"] for b in daily], [
                ds("Premium accounts created", [approved_by_date.get(d, 0) for d in dates], "green"),
                ds("Waiting for G2 approval", [g2_by_date.get(d, 0) for d in dates], "amber")]),
        },
        "has_status": bool(codes),
    }


def drill_success(scope):
    daily = series(scope.metrics, "daily")
    return {"rows": daily, "totals": totals(scope.metrics) if scope.metrics else None}


# ---------- reports ----------
REPORT_KINDS = {"registration": "Registration performance", "errors": "Error report",
                "kyc": "KYC performance", "accounts": "Premium and Lite accounts"}


def _status_by_bucket(status, grain):
    out = defaultdict(list)
    for s in status:
        out[bucket_key(s["date"], grain)].append(s)
    return out


def report(scope, kind, grain):
    ser = series(scope.metrics, grain)
    sb = _status_by_bucket(scope.status, grain)
    title = f"{REPORT_KINDS[kind]} - {GRAIN_LABELS[grain].lower()}"
    rows = []
    if kind == "registration":
        cols = [("Period", "text"), ("Applications", "int"), ("Successful", "int"), ("Unsuccessful", "int"),
                ("Success rate", "pct"), ("Growth", "growth")]
        rows = [[b["label"], b["total"], b["registered"], b["not_registered"], b["rate"], b["growth"]] for b in ser]
    elif kind == "accounts":
        cols = [("Period", "text"), ("Lite", "int"), ("Premium", "int"), ("Premium : Lite", "ratio"), ("Premium share", "pct")]
        rows = [[b["label"], b["lite"], b["premium"], pct(b["premium"], b["lite"]), pct(b["premium"], b["registered"])]
                for b in ser]
    elif kind == "errors":
        cols = [("Period", "text"), ("Verification errors", "int"), ("Rejected", "int"), ("Top error", "text"),
                ("Top error count", "int")]
        for b in ser:
            st = sb.get(b["key"], [])
            codes, groups = status_summary(st)
            top = top_errors(st, 1)
            rows.append([b["label"], groups.get("verification_error", 0) if st else None, groups.get("rejected", 0) if st else None,
                         top[0]["label"] if top else "-", top[0]["count"] if top else None])
    else:  # kyc
        cols = [("Period", "text"), ("KYC attempts", "int"), ("Passed", "int"), ("Failed", "int"),
                ("Outstanding", "int"), ("Pass rate", "pct"), ("Compliance rate", "pct")]
        for b in ser:
            k = kyc(sb.get(b["key"], []))
            rows.append([b["label"]] + ([k["attempts"], k["passed"], k["failed"], k["outstanding"], k["pass_rate"],
                                         k["compliance_rate"]] if k else [None] * 6))
    return {"title": title, "columns": cols, "rows": rows}


def fmt(value, kind):
    if value is None:
        return "-"
    if kind == "int":
        return f"{int(value):,}"
    if kind == "pct":
        return f"{value * 100:.1f}%"
    if kind == "growth":
        return f"{value:+.1f}%"
    if kind == "ratio":
        return f"{value:.2f}"
    return str(value)
