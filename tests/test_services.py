import io
import unittest
from datetime import date, datetime

from openpyxl import Workbook

from app.services.parser import parse_workbook, resolve_status_dates
from app.services.validation import validate


def build_workbook(total_on_day3=589):
    """A small workbook shaped like the daily health-check, with month/day-swapped status headers."""
    wb = Workbook()
    reg = wb.active
    reg.title = "Registration_status"
    reg.append(["Date", "Lite", "Premium", "Successful", "Not registered", "Total", "Rate"])
    rows = [(4, 37, 18, 12, 67), (5, 63, 21, 6, 90), (6, 328, 57, 204, total_on_day3),
            (7, 100, 81, 45, 226), (8, 120, 77, 100, 297), (9, 100, 0, 60, 160), (10, 70, 1, 8, 79)]
    for day, lite, prem, notreg, total in rows:
        reg.append([datetime(2026, 5, day), lite, prem, lite + prem, notreg, total, 0.8])

    status = wb.create_sheet("Sheet1")
    # Excel read 4/5/2026 (4 May) as 5 April: month and day are swapped in the header.
    status.append(["Date"] + [datetime(2026, d, 5) if d != 5 else datetime(2026, 5, 5) for d in (4, 5, 6, 7, 8, 9, 10)])
    status.append(["Registration Status"])
    per_day = {4: (49, 18), 5: (69, 21), 6: (586, 57), 7: (145, 81), 8: (220, 77), 9: (160, 0), 10: (78, 1)}
    status.append(['NOT_COMPLETED("0", "Not completed"),'] + [per_day[d][0] for d in per_day])
    status.append(['ACCEPTED("30", "Account created"),'] + [per_day[d][1] for d in per_day])
    status.append(["Total Count"] + [sum(per_day[d]) for d in per_day])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


class DateResolution(unittest.TestCase):
    def test_swapped_headers_are_corrected(self):
        known = {date(2026, 5, d) for d in range(4, 11)}
        headers = [datetime(2026, m, 5) for m in range(4, 11)]
        dates, warning = resolve_status_dates(headers, known)
        self.assertEqual(dates[0], date(2026, 5, 4))
        self.assertEqual(dates[-1], date(2026, 5, 10))
        self.assertIsNotNone(warning)

    def test_correct_headers_untouched(self):
        known = {date(2026, 5, 4), date(2026, 5, 5)}
        dates, warning = resolve_status_dates([datetime(2026, 5, 4), datetime(2026, 5, 5)], known)
        self.assertEqual(dates, [date(2026, 5, 4), date(2026, 5, 5)])
        self.assertIsNone(warning)


class ParserAndRules(unittest.TestCase):
    def test_parse_and_reconcile(self):
        parsed = parse_workbook(build_workbook())
        self.assertEqual(len(parsed.metrics), 7)
        self.assertEqual(parsed.status_labels["30"], "Account created")
        self.assertIn(date(2026, 5, 6), parsed.status_counts)

    def test_total_mismatch_flagged(self):
        parsed = parse_workbook(build_workbook(total_on_day3=589))
        issues = validate(parsed.metrics, parsed.status_counts, parsed.control_totals)
        mismatches = [i for i in issues if i.rule == "TOTAL_MISMATCH"]
        self.assertEqual([i.report_date for i in mismatches], [date(2026, 5, 6)])
        self.assertEqual(mismatches[0].severity, "critical")

    def test_clean_report_has_no_critical_findings(self):
        parsed = parse_workbook(build_workbook())
        # Correct the registration sheet so it agrees with the status breakdown on 6 May.
        parsed.metrics[date(2026, 5, 6)]["not_registered"] += 54
        parsed.metrics[date(2026, 5, 6)]["total_reported"] = 643
        issues = validate(parsed.metrics, parsed.status_counts, parsed.control_totals)
        self.assertFalse([i for i in issues if i.severity == "critical"])


if __name__ == "__main__":
    unittest.main()


# ---------------- v2: analytics, extras CSV, exports ----------------
from app.services import calc, exports  # noqa: E402
from app.services.extras import parse_extras_csv  # noqa: E402


def scope_from_workbook():
    parsed = parse_workbook(build_workbook())
    metrics = [{"market": "DRC", "date": d, "lite": v["lite"], "premium": v["premium"],
                "not_registered": v["not_registered"], "total": v["total_reported"]} for d, v in parsed.metrics.items()]
    status = [{"market": "DRC", "date": d, "code": c, "label": parsed.status_labels[c], "count": n}
              for d, cs in parsed.status_counts.items() for c, n in cs.items()]
    return calc.Scope(metrics=metrics, status=status, days=30)


class Analytics(unittest.TestCase):
    def test_overview_totals(self):
        k = calc.overview(scope_from_workbook(), "daily")["kpi"]
        self.assertEqual(k["total"], sum(m["total"] for m in scope_from_workbook().metrics))
        self.assertAlmostEqual(k["rate"], k["registered"] / k["total"])

    def test_weekly_bucket_groups_a_week(self):
        ser = calc.series(scope_from_workbook().metrics, "weekly")
        self.assertEqual(len(ser), 1)
        self.assertEqual(ser[0]["days"], 7)

    def test_unavailable_metrics_are_none_not_invented(self):
        sc = scope_from_workbook()
        self.assertIsNone(calc.executive(sc)["kpi"]["cac"])
        self.assertIsNone(calc.executive(sc)["kpi"]["satisfaction"])
        self.assertIsNone(calc.monetization(sc)["kpi"]["avg_tx"])
        self.assertIsNone(calc.operational(sc)["stages"])

    def test_extras_switch_metrics_on(self):
        sc = scope_from_workbook()
        sc.extras = [{"market": "DRC", "date": date(2026, 5, 4), "metric": "acquisition_cost", "dimension": "", "value": 1000.0}]
        registered = calc.totals(sc.metrics)["registered"]
        self.assertAlmostEqual(calc.executive(sc)["kpi"]["cac"], 1000.0 / registered)

    def test_kyc_buckets_add_up(self):
        k = calc.kyc(scope_from_workbook().status)
        self.assertEqual(k["attempts"], k["passed"] + k["failed"] + k["outstanding"])

    def test_reports_export(self):
        sc = scope_from_workbook()
        for kind in calc.REPORT_KINDS:
            rep = calc.report(sc, kind, "daily")
            self.assertEqual(len(rep["rows"]), 7)
            self.assertEqual(exports.to_xlsx(rep, "x")[:2], b"PK")
            self.assertEqual(exports.to_pdf(rep, "x")[:4], b"%PDF")


class ExtrasCsv(unittest.TestCase):
    GOOD = b"date,market,metric,dimension,value\n2026-05-04,DRC,acquisition_cost,,100\n2026-05-04,DRC,channel_registrations,Mobile app,5\n"

    def test_valid_file(self):
        rows, errors = parse_extras_csv(self.GOOD, {"DRC"})
        self.assertEqual((len(rows), errors), (2, []))

    def test_rejects_unknown_market_and_missing_dimension(self):
        bad = b"date,market,metric,dimension,value\n2026-05-04,XXX,transactions,,5\n2026-05-04,DRC,stage_dropoff,,5\n"
        rows, errors = parse_extras_csv(bad, {"DRC"})
        self.assertEqual(len(errors), 2)

    def test_rejects_out_of_range_satisfaction(self):
        rows, errors = parse_extras_csv(b"date,market,metric,dimension,value\n2026-05-04,DRC,satisfaction_score,,9\n", {"DRC"})
        self.assertTrue(errors)


if __name__ == "__main__":  # re-run guard for the appended tests
    unittest.main()
