"""Pure validation rules. No Flask or database imports, so they are easy to unit test."""
from dataclasses import dataclass
from statistics import median
from typing import Optional

RULE_LABELS = {
    "TOTAL_MISMATCH": "Totals reconcile across sheets",
    "ARITHMETIC": "Lite + Premium + Not registered = Total",
    "CONTROL_TOTAL": "Status rows match the report's own total",
    "MISSING_STATUS_DATA": "Status breakdown present",
    "PREMIUM_ACCEPTED_GAP": "Premium accounts = accepted status",
    "APPROVAL_BACKLOG": "No approval backlog",
    "FACE_MATCH_SPIKE": "No selfie-vs-ID error spike",
    "SUCCESS_RATE_DROP": "Success rate in normal range",
}

MIN_HISTORY_DAYS = 5


@dataclass
class Issue:
    report_date: object
    rule: str
    severity: str
    message: str
    expected: Optional[str] = None
    actual: Optional[str] = None


def _success_rate(m):
    total = m["total_reported"]
    return (m["lite"] + m["premium"]) / total if total else None


def validate(metrics, status_counts, status_control_totals=None):
    """
    metrics: {date: {lite, premium, not_registered, total_reported}}
    status_counts: {date: {status_code: count}}
    status_control_totals: {date: reported "Total Count" row value}
    """
    status_control_totals = status_control_totals or {}
    issues = []

    for day in sorted(metrics):
        m = metrics[day]
        computed_total = m["lite"] + m["premium"] + m["not_registered"]
        if computed_total != m["total_reported"]:
            issues.append(Issue(
                day, "ARITHMETIC", "critical",
                f"Lite + Premium + Not registered adds up to {computed_total}, but the reported total is {m['total_reported']}.",
                str(computed_total), str(m["total_reported"])))

        codes = status_counts.get(day)
        if not codes:
            issues.append(Issue(day, "MISSING_STATUS_DATA", "warning",
                                "No status breakdown was found for this date, so totals could not be cross-checked."))
            continue

        status_sum = sum(codes.values())
        if status_sum != m["total_reported"]:
            diff = status_sum - m["total_reported"]
            issues.append(Issue(
                day, "TOTAL_MISMATCH", "critical",
                f"Registration sheet reports {m['total_reported']} applications but the status breakdown sums to "
                f"{status_sum} ({diff:+d}). One of the two sources is wrong or incomplete.",
                str(m["total_reported"]), str(status_sum)))

        control = status_control_totals.get(day)
        if control is not None and control != status_sum:
            issues.append(Issue(
                day, "CONTROL_TOTAL", "warning",
                f"The status rows sum to {status_sum} but the report's own 'Total Count' row says {control}.",
                str(control), str(status_sum)))

        accepted = codes.get("30", 0)
        if accepted != m["premium"]:
            issues.append(Issue(
                day, "PREMIUM_ACCEPTED_GAP", "info",
                f"Premium accounts ({m['premium']}) differ from the 'Account created' status ({accepted}). "
                "Confirm how Lite accounts are meant to be counted.",
                str(m["premium"]), str(accepted)))

    issues.extend(_anomaly_rules(metrics, status_counts))
    return issues


def _anomaly_rules(metrics, status_counts):
    days = sorted(metrics)
    if len(days) < MIN_HISTORY_DAYS:
        return []

    issues = []
    rates = [r for r in (_success_rate(metrics[d]) for d in days) if r is not None]
    median_rate = median(rates) if rates else None
    median_accepted = median(status_counts.get(d, {}).get("30", 0) for d in days)
    median_g2 = median(status_counts.get(d, {}).get("60", 0) for d in days)
    median_face = median(status_counts.get(d, {}).get("21", 0) for d in days)

    for day in days:
        codes = status_counts.get(day, {})
        accepted, g2, face = codes.get("30", 0), codes.get("60", 0), codes.get("21", 0)

        if median_accepted >= 5 and accepted < 0.25 * median_accepted and g2 > max(2 * median_g2, 5):
            issues.append(Issue(
                day, "APPROVAL_BACKLOG", "warning",
                f"Only {accepted} accounts were created (typical: {median_accepted:g}) while {g2} applications sat in "
                f"'Pending G2 approval' (typical: {median_g2:g}). Accounts may be blocked at the approval step.",
                f"~{median_accepted:g} accepted", f"{accepted} accepted / {g2} pending G2"))

        if face >= 10 and face > 4 * max(median_face, 1):
            issues.append(Issue(
                day, "FACE_MATCH_SPIKE", "warning",
                f"{face} ID-photo vs selfie failures against a typical {median_face:g}. "
                "Check for a campaign spike, a capture-quality issue or a model change.",
                f"~{median_face:g}", str(face)))

        rate = _success_rate(metrics[day])
        if rate is not None and median_rate is not None and metrics[day]["total_reported"] >= 30 \
                and rate < median_rate - 0.10:
            issues.append(Issue(
                day, "SUCCESS_RATE_DROP", "warning",
                f"Success rate was {rate:.1%} against a typical {median_rate:.1%}.",
                f"{median_rate:.1%}", f"{rate:.1%}"))
    return issues
