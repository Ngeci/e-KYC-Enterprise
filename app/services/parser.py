"""Reads the daily health-check workbook. No Flask or database imports."""
import re
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

STATUS_PATTERN = re.compile(r'\(\s*"(?P<code>\d+)"\s*,\s*"(?P<label>[^"]+)"\s*\)')


class ParseError(Exception):
    pass


@dataclass
class ParsedReport:
    metrics: dict = field(default_factory=dict)          # {date: {...}}
    status_counts: dict = field(default_factory=dict)    # {date: {code: count}}
    status_labels: dict = field(default_factory=dict)    # {code: label}
    control_totals: dict = field(default_factory=dict)   # {date: reported total row}
    warnings: list = field(default_factory=list)


def _to_int(value):
    number = pd.to_numeric(value, errors="coerce")
    return 0 if pd.isna(number) else int(number)


def _find_sheet(names, *needles):
    for name in names:
        lowered = name.strip().lower().replace(" ", "_")
        if any(n in lowered for n in needles):
            return name
    return None


def resolve_status_dates(header_dates, metric_dates):
    """
    The status sheet's header dates are frequently stored as month/day instead of day/month
    (4 May becomes 5 April). Align them to the registration sheet's dates.
    Returns (dates, warning_or_None).
    """
    headers = [pd.Timestamp(h).date() for h in header_dates]
    known = set(metric_dates)

    if all(h in known for h in headers):
        return headers, None

    swapped = []
    for h in headers:
        try:
            swapped.append(date(h.year, h.day, h.month))
        except ValueError:
            swapped.append(None)
    if None not in swapped and all(s in known for s in swapped):
        return swapped, ("Status-sheet header dates were stored month/day instead of day/month; "
                         "they were corrected using the registration sheet.")

    ordered = sorted(known)
    if len(headers) == len(ordered):
        return ordered, "Status-sheet dates did not match the registration sheet and were aligned by column position."

    return headers, "Status-sheet dates could not be aligned with the registration sheet."


def parse_workbook(file_obj):
    try:
        xl = pd.ExcelFile(file_obj, engine="openpyxl")
    except Exception as exc:  # corrupt or not an xlsx file
        raise ParseError("The file could not be read as an Excel workbook.") from exc

    report = ParsedReport()

    reg_name = _find_sheet(xl.sheet_names, "registration_status")
    if not reg_name:
        raise ParseError("No 'Registration_status' sheet found.")
    reg = xl.parse(reg_name, header=0)
    if reg.shape[1] < 6:
        raise ParseError("'Registration_status' needs at least 6 columns (date, lite, premium, successful, not registered, total).")

    dates = pd.to_datetime(reg.iloc[:, 0], errors="coerce", dayfirst=True)
    for idx, stamp in dates.items():
        if pd.isna(stamp):
            continue
        row = reg.iloc[idx]
        report.metrics[stamp.date()] = {
            "lite": _to_int(row.iloc[1]),
            "premium": _to_int(row.iloc[2]),
            "not_registered": _to_int(row.iloc[4]),
            "total_reported": _to_int(row.iloc[5]),
        }
    if not report.metrics:
        raise ParseError("No dated rows found in 'Registration_status'.")

    for name in xl.sheet_names:
        if name == reg_name:
            continue
        raw = xl.parse(name, header=None)
        if raw.empty or str(raw.iat[0, 0]).strip().lower() != "date":
            continue
        _parse_status_sheet(raw, report)
        break
    else:
        report.warnings.append("No status breakdown sheet found; cross-checks were skipped.")

    return report


def _parse_status_sheet(raw, report):
    header = raw.iloc[0, 1:]
    columns = [i for i, v in header.items() if not pd.isna(pd.to_datetime(v, errors="coerce"))]
    header_dates = [pd.to_datetime(header[i]) for i in columns]
    dates, warning = resolve_status_dates(header_dates, report.metrics.keys())
    if warning:
        report.warnings.append(warning)

    for _, row in raw.iloc[1:].iterrows():
        label_cell = row.iloc[0]
        if pd.isna(label_cell):
            continue
        text = str(label_cell).strip()

        if text.lower().startswith("total"):
            for col, day in zip(columns, dates):
                value = pd.to_numeric(row.iloc[col], errors="coerce")
                if not pd.isna(value):
                    report.control_totals[day] = int(value)
            continue

        match = STATUS_PATTERN.search(text)
        if not match:
            continue
        code, label = match.group("code"), match.group("label")
        report.status_labels[code] = label
        for col, day in zip(columns, dates):
            report.status_counts.setdefault(day, {})[code] = _to_int(row.iloc[col])
