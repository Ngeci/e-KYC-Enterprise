"""CSV intake for business data that the daily workbook does not contain. Pure parsing, no database."""
import csv
import io
from datetime import datetime

# metric -> (needs a dimension?, label shown in the template and errors)
METRICS = {
    "acquisition_cost": (False, "Marketing/acquisition spend for the day (same currency throughout)"),
    "transactions": (False, "Number of customer transactions that day"),
    "satisfaction_score": (False, "Average customer satisfaction score from 1 to 5"),
    "channel_registrations": (True, "Registrations from one channel (dimension = channel name)"),
    "stage_dropoff": (True, "Customers who abandoned at one stage (dimension = stage name)"),
    "product_customers": (True, "Customers using one product (dimension = product name)"),
}

TEMPLATE = (
    "date,market,metric,dimension,value\n"
    "2026-05-04,DRC,acquisition_cost,,1250.50\n"
    "2026-05-04,DRC,transactions,,3400\n"
    "2026-05-04,DRC,satisfaction_score,,4.2\n"
    "2026-05-04,DRC,channel_registrations,Mobile app,52\n"
    "2026-05-04,DRC,stage_dropoff,Document upload,9\n"
    "2026-05-04,DRC,product_customers,Airtime,210\n"
)


def _parse_date(text):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            pass
    return None


def parse_extras_csv(raw_bytes, market_codes):
    """Returns (rows, errors). Rows are only trusted when errors is empty."""
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], ["The file is not UTF-8 text. Save it as CSV (UTF-8)."]
    reader = csv.DictReader(io.StringIO(text))
    expected = {"date", "market", "metric", "dimension", "value"}
    if not reader.fieldnames or not expected.issubset({(f or "").strip().lower() for f in reader.fieldnames}):
        return [], ["Header must be: date,market,metric,dimension,value"]

    rows, errors = [], []
    for line, raw in enumerate(reader, start=2):
        rec = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(rec.values()):
            continue
        day = _parse_date(rec["date"])
        code = rec["market"].upper()
        metric = rec["metric"].lower()
        try:
            value = float(rec["value"])
        except ValueError:
            value = None
        problem = None
        if day is None:
            problem = f"invalid date '{rec['date']}'"
        elif code not in market_codes:
            problem = f"unknown market '{rec['market']}'"
        elif metric not in METRICS:
            problem = f"unknown metric '{rec['metric']}'"
        elif value is None or value < 0:
            problem = "value must be a non-negative number"
        elif metric == "satisfaction_score" and not 1 <= value <= 5:
            problem = "satisfaction_score must be between 1 and 5"
        elif METRICS[metric][0] and not rec["dimension"]:
            problem = f"{metric} needs a dimension"
        if problem:
            errors.append(f"Line {line}: {problem}")
            continue
        rows.append({"date": day, "market": code, "metric": metric,
                     "dimension": rec["dimension"][:80] if METRICS[metric][0] else "", "value": value})
    if not rows and not errors:
        errors.append("The file has no data rows.")
    return rows, errors[:15]
