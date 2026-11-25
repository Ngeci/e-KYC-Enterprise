# e-KYC Dashboard — Enterprise Edition (v2)

Monitoring, analytics, reporting and user management for electronic KYC onboarding across markets.
Black, white and green interface with dark/light mode, collapsible sidebar, working notifications and Excel/PDF reports.
**Every number comes from imported data. Anything the data cannot support shows "Not available" and says what to upload.**

## Modules

| Module | What it shows | Who (default) |
|---|---|---|
| Dashboard | Registrations, growth, success rate, failures, errors, Lite/Premium, KYC pass rate, completion rate, daily/weekly/monthly/yearly trends, 5 charts. Success rate and KYC pass rate are clickable drill-downs | all roles |
| Executive | Performance summary, KPIs incl. CAC, KYC compliance, satisfaction stars, last five days, growth comparisons, monthly/yearly tables, top five errors, market comparison | admin, executive |
| Monetization | Lite/Premium, ratio, customer growth, distribution, CAC, transactions per customer, favourite product, adoption trends | admin, executive |
| Upgrade | Lite-to-Premium pipeline: Premium share, accounts waiting for review or G2 approval, approval backlog over time | admin, executive, staff |
| Operational | Completion and drop-off, errors and error trend, stage drop-off, channels, validation findings | all roles |
| Reports | Registration, error, KYC and account reports by day/week/month/year with Excel and PDF download | admin, executive, staff |
| Data sources | Import the daily Excel report; upload business data CSV | admin, staff |
| Notifications | Bell with unread count, history, mark read / all read, admin announcements, role alerts, account messages | all roles |
| User Management | Add, edit, activate/deactivate, reset or force password change, delete, per-role module permissions, markets, audit log | admin only |
| Settings | Profile, password, appearance | all roles |

Admins can change which modules each role may open under **User Management > Manage access permissions**.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export APP_ENV=development FLASK_APP=wsgi.py            # Windows: set instead of export
flask init-db
flask create-admin your.name
flask add-market DRC "Vodacom DRC" --country "DR Congo"
flask run                                                # http://127.0.0.1:5000
```
Then sign in, open **Data sources** and import your Excel report. Production: set `APP_ENV=production`, a strong `SECRET_KEY`, a MySQL `DATABASE_URL` (see `.env.example`), serve over HTTPS, and run `docker compose up` or `gunicorn wsgi:app`. Use `flask db init / migrate / upgrade` for schema changes.

## Data you must supply for the remaining metrics

The daily workbook has no cost, transaction, survey, channel, stage or product data. Upload a CSV (template on the Data sources page):

`date,market,metric,dimension,value` with metric one of `acquisition_cost`, `transactions`, `satisfaction_score` (1-5), `channel_registrations`, `stage_dropoff`, `product_customers` (the last three need a dimension). Until then those cards read "Not available".
CAC = total acquisition spend / registered customers in the period.

## Definitions (change in `app/services/statuses.py` and `calc.py`)

- **Registrations** = applications reported. **Success rate** = (Lite + Premium) / applications. **Growth** = last 7 days vs the 7 before when there are 14+ days, otherwise latest day vs the day before (labelled as such).
- **Errors** = verification-error statuses. **Completion rate** = 1 - abandoned share. **Drop-off** = abandoned share.
- **KYC pass rate** = "Account created" / attempts (attempts exclude abandoned). **Compliance rate** = passed / (passed + failed). These describe the full-KYC (Premium) status flow because Lite accounts have no status of their own in the report. **Confirm with your compliance team before quoting externally.**

## Security

Hashed passwords, 5-attempt lockout, 30-minute idle timeout, CSRF on every state change, CSP and security headers, server-side role and module checks, audit log of sign-ins, imports, exports and admin actions, forced password change at first sign-in. Deleting a user anonymises the account and keeps its audit history; it never removes rows.

## Validation engine

Eight automated checks run on every import (cross-sheet totals, arithmetic, control totals, Premium vs Accepted, approval backlog, selfie-vs-ID spike, success-rate drop). Critical findings notify admins, executives and staff.

## Tests

`python -m unittest tests.test_services` (parser, validation rules, analytics, CSV intake, Excel/PDF export).

## Not included

SSO and MFA, Kafka streaming ingestion, real-time push (notifications refresh on page load; Flask-SocketIO can be added), scheduled report emails.
