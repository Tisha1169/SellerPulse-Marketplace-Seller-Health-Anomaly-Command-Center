# Deployment

Target: **GitHub → Streamlit Community Cloud → cloud PostgreSQL**, per the plan
validated in this doc. Everything here has been tested locally end-to-end
(against a stand-in cloud Postgres on a different port) before being handed off
as instructions — the only steps that require your own accounts (a cloud
Postgres provider, Streamlit Community Cloud, GitHub) are the ones I can't run
myself.

## The size problem, and how it's solved

The full local dataset is **~2.9GB** — too large for any reasonable Postgres
free tier. Rather than trim the analytical dataset itself, I checked exactly
which tables `streamlit_app/app.py` queries (`grep -n "FROM core\." streamlit_app/app.py`)
and found:

- `fact_orders` (571MB), `fact_shipments` (425MB), `fact_returns` (20MB),
  `fact_reviews` (52MB) — **~1.07GB combined**, and the app only ever ran
  `COUNT(*)` against them for 4 headline KPIs. Replaced by
  `core.dataset_summary`, a one-row-per-metric table populated once by
  `pipeline/populate_dataset_summary.py` — same numbers, zero row-level data
  shipped.
- `seller_metric_rolling_baseline` (747MB) — **not queried by the app at all**.
- `dim_product`, `dim_customer`, `dim_date`, `ground_truth_anomalies` — not
  queried by the app (the evaluation report is a static markdown file the app
  reads from disk, not a live query against ground truth).
- `seller_metric_cohort_baseline` (898MB, 5.16M rows) — the app only ever
  queries the latest day (Seller 360) or trailing 30 days (Seller Risk
  Intelligence), so it's trimmed to a **60-day trailing window** at export
  time (1.05M rows, ~180MB) — margin above what's actually queried.

Result: **~2.9GB → 416MB**, verified by actually running the export
(`deployment/export_cloud_dataset.py`) against a throwaway local Postgres
container standing in for the cloud target — see the commit history for the
real numbers from that run. Zero dashboard functionality is lost; every tab
was re-verified against the reduced database in the browser before writing
this doc.

## Before deploying: verify locally with pinned dependencies

`requirements.txt` pins exact versions (not `>=` ranges) so the cloud build
reproduces the environment this was actually tested against, rather than
resolving to whatever's newest on deploy day. Verify that pin set actually
works end-to-end in a completely isolated environment before pushing —
don't rely on your existing dev `.venv`, which may have picked up extra
packages over time that mask a missing dependency:

```bash
python3 -m venv /tmp/clean_check && source /tmp/clean_check/bin/activate
pip install -r requirements.txt
pytest tests/                              # must be 35/35
streamlit run streamlit_app/app.py         # confirm it boots with no import errors
deactivate && rm -rf /tmp/clean_check
```

This also exercises the same import paths (`sys.path.insert` in
`streamlit_app/app.py`, package resolution for `anomaly_engine`/`scoring`/etc.)
that Streamlit Community Cloud's build will use — a clean venv is the closest
local approximation of that build environment.

### Connection health check

`streamlit_app/app.py` runs a `SELECT 1` against the configured database
before rendering anything else. If it fails, the app shows one readable error
message (which `DATABASE_URL` source to check, and the exception *type* only —
never the raw exception text, since some drivers embed the DSN/host/password
in their error strings) instead of five different tabs each throwing their own
raw traceback. This is what a misconfigured or missing `DATABASE_URL` secret
on Streamlit Community Cloud will look like to anyone opening the deployed
app — verified by pointing the app at a deliberately unreachable database and
confirming the clean error renders instead of a stack trace.

## Step 1 — Provision a free cloud Postgres

Any of these work (all have historically offered a free tier comfortably
above 416MB — check current limits before committing, they change):
[Neon](https://neon.tech), [Supabase](https://supabase.com), or
[Render](https://render.com). Create a database, copy its connection string
(format: `postgresql://user:password@host:port/dbname`).

## Step 2 — Export the reduced dataset

From your local machine, with the local Postgres running (`docker compose up -d`)
and populated (`python -m pipeline.run_daily_pipeline` at least once):

```bash
export CLOUD_DATABASE_URL="postgresql://user:password@host:port/dbname"
python -m deployment.export_cloud_dataset
```

This builds `deployment/cloud_schema.sql` on the target and streams the
reduced tables over. Takes under 15 seconds at this project's scale. Prints
the resulting cloud database size at the end — confirm it's comfortably under
your provider's limit before proceeding.

## Step 3 — Push to GitHub

Already done throughout this project's build — confirm `main` is up to date:

```bash
git push origin main
```

## Step 4 — Deploy on Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub.
2. "New app" → select this repo → branch `main` → main file path `streamlit_app/app.py`.
3. Before deploying, open **Advanced settings → Secrets** and paste:
   ```toml
   DATABASE_URL = "postgresql://user:password@host:port/dbname"
   ```
   (the same cloud connection string from Step 1 — this is what
   `anomaly_engine/db.py`'s `_url_from_streamlit_secrets()` picks up
   automatically; nothing else needs to change in the app for it to find this).
4. Deploy. First build installs `requirements.txt` (includes `plotly`,
   `streamlit`, `sqlalchemy`, `psycopg2-binary`) — no additional system
   packages needed since `psycopg2-binary` ships its own libpq.

## Step 5 — Verify the deployed app

Checklist (all 5 tabs, matching what was verified locally against the reduced
dataset before this doc was written):
- Executive Overview: KPI numbers match `dataset_summary` (2,000 sellers,
  3.43M orders, etc. — these are fixed historical counts, not live-changing).
- Seller Risk Intelligence: top-risk table populates, peer-cohort heatmap
  renders (confirms the trimmed `seller_metric_cohort_baseline` data is present).
- Anomaly Intelligence: trend/type/method charts populate; the ground-truth
  evaluation section renders (reads `docs/evaluation_report.md` from the repo
  checkout, not the database — always present after deploy).
- Investigation Operations: queue loads, filtering works, a case-status update
  writes back successfully (confirms write access to the cloud DB, not just
  read).
- Seller 360: seller selector populates, all sections render for a sample
  seller.

## Local development is unaffected

`docker compose up -d` + `.env` (`POSTGRES_HOST=localhost`, etc.) continues to
work exactly as before — `anomaly_engine/db.py` only reaches for Streamlit
secrets or `DATABASE_URL` if they're present, falling back to the original
discrete `POSTGRES_*` variables otherwise. Full local functionality (3.4M-row
dataset, the daily pipeline, all 35 tests) requires the full local database,
not the reduced cloud one — the reduced dataset exists solely for the public
demo's read-mostly dashboard use case.

## What's NOT deployed

The reduced cloud database does not support re-running
`pipeline/run_daily_pipeline.py`'s generation/detection/scoring stages (it's
missing the raw fact tables those stages read from) — the cloud deployment is
a **read-mostly demo of the dashboard**, not a live re-run of the full
pipeline. That's an intentional scope boundary, not an oversight: the pipeline
and its 35 tests are meant to be run and demonstrated locally (per
`README.md`), while the cloud deployment's job is letting a recruiter click a
link and explore the results.
