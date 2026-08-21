# Power BI Specification (not built — spec only)

Per the Phase 1 decision: Streamlit + Plotly is the live, deployed dashboard for this
project (no macOS-native Power BI Desktop, and a live app serves a public portfolio
demo better than a static/embedded report). This document is a complete enough spec
that the `.pbix` can be built later on Windows **without re-deriving any analytics** —
every measure below maps to a column that already exists in `core.fact_seller_daily_metrics`,
`core.seller_health_score`, `core.investigation_tickets`, or `core.fact_anomaly_flags`.
Power BI's role here is presentation, not recomputation.

## Data source

Connect Power BI Desktop's PostgreSQL connector directly to the same database the
Streamlit app uses (local `docker compose` instance, or the reduced cloud instance
from `deployment/cloud_schema.sql` — either works, since Power BI would read the same
tables the app already queries).

## Data model (tables to import)

Import mode (not DirectQuery, given the dataset scale) for:

| Table | Role |
|---|---|
| `dim_seller` | Dimension — segment, tenure cohort, category, region |
| `fact_seller_daily_metrics` | Fact — the daily KPI spine |
| `fact_anomaly_flags` | Fact — filter to `method = 'Ensemble'` at import for the dashboard-facing model (keep a separate query for the raw multi-method comparison page) |
| `seller_health_score` | Fact — one row per seller per day |
| `investigation_tickets` | Fact — join to `fact_anomaly_flags` on `primary_flag_id` for anomaly_type/affected_metric |
| `seller_metric_cohort_baseline` | Fact — only needed for the seller drill-down page; import filtered to the trailing 90 days to keep the `.pbix` file size reasonable |

## Relationships

```
dim_seller (seller_id) [1] ---- [*] fact_seller_daily_metrics (seller_id)
dim_seller (seller_id) [1] ---- [*] seller_health_score (seller_id)
dim_seller (seller_id) [1] ---- [*] fact_anomaly_flags (seller_id)
dim_seller (seller_id) [1] ---- [*] investigation_tickets (seller_id)
fact_anomaly_flags (flag_id) [1] ---- [*] investigation_tickets (primary_flag_id)
dim_seller (seller_id) [1] ---- [*] seller_metric_cohort_baseline (seller_id)
```

All single-direction (dim_seller as the "one" side) except `fact_anomaly_flags` →
`investigation_tickets`, which is also one-to-many on `flag_id`.

A separate **Date table** should be created (`CALENDAR()` DAX function spanning the
data's date range) and marked as the official date table, with relationships to
`metric_date` / `flag_date` / `score_date` / `detected_date` — none of those columns
should be the "active" relationship simultaneously; use `USERELATIONSHIP()` in
measures that need a non-default one (e.g., `detected_date` for ticket-based measures
while `metric_date` stays the default active relationship for KPI trend visuals).

## DAX measures

```dax
Total Sellers = DISTINCTCOUNT(dim_seller[seller_id])

Healthy Sellers =
CALCULATE(
    DISTINCTCOUNT(seller_health_score[seller_id]),
    seller_health_score[health_tier] = "Healthy",
    seller_health_score[score_date] = MAX(seller_health_score[score_date])
)
-- repeat pattern for Watch / At_Risk / Critical

Avg Health Score =
CALCULATE(
    AVERAGE(seller_health_score[health_score]),
    seller_health_score[score_date] = MAX(seller_health_score[score_date])
)

Active Investigations =
CALCULATE(
    COUNTROWS(investigation_tickets),
    investigation_tickets[status] IN {"New", "Investigating", "Action_Required"}
)

SLA Breach Rate =
DIVIDE(
    CALCULATE(COUNTROWS(investigation_tickets), investigation_tickets[is_sla_breached] = TRUE),
    COUNTROWS(investigation_tickets)
)

Avg Resolution Hours =
AVERAGEX(
    FILTER(investigation_tickets, NOT ISBLANK(investigation_tickets[resolved_at])),
    DATEDIFF(investigation_tickets[detected_date], investigation_tickets[resolved_at], HOUR)
)

Ensemble Flags (Period) = COUNTROWS(fact_anomaly_flags)  -- fact_anomaly_flags filtered to method='Ensemble' at import

Ensemble Flags Prior Period =
CALCULATE([Ensemble Flags (Period)], DATEADD('Date'[Date], -1, MONTH))

Anomaly Trend MoM % =
DIVIDE([Ensemble Flags (Period)] - [Ensemble Flags Prior Period], [Ensemble Flags Prior Period])

GMV at Risk =
CALCULATE(
    SUM(fact_seller_daily_metrics[gmv]),
    TREATAS(VALUES(seller_health_score[seller_id]), fact_seller_daily_metrics[seller_id]),
    seller_health_score[health_tier] IN {"At_Risk", "Critical"}
)
```

## Recommended page structure

Mirrors the Streamlit app's information architecture — same 5 sections, so the two
artifacts stay conceptually interchangeable rather than diverging designs:

### Page 1 — Executive Marketplace Health
- KPI card row: Total Sellers, Total Orders (from a small imported summary table
  mirroring `core.dataset_summary`), Active Investigations, SLA Breach Rate
- Health tier stacked/clustered column chart (Healthy/Watch/At_Risk/Critical)
- Health Score distribution (histogram — Power BI needs a calculated-column bucket
  approach or the "Histogram" custom visual, since native histogram support is limited)
- Anomaly trend line chart over time (Ensemble flags/day)
- Slicers: date range, seller segment, category

### Page 2 — Seller Risk Intelligence
- Table/matrix: top-N sellers by Health Score ascending, with defect/late-shipment/
  return rate, anomaly count, open priority score as columns
- Bar chart: anomaly frequency by seller (top 15)
- Matrix visual (as a heatmap via conditional formatting) for peer-cohort deviation:
  rows = seller, columns = metric_name, values = avg cohort z-score
- Slicers: tenure cohort, segment, category, min anomaly count

### Page 3 — Anomaly Intelligence
- Stacked area chart: anomaly flags by type over time (weekly)
- Bar chart: anomaly type breakdown
- Bar chart: detection method comparison (raw flag volume by method)
- A dedicated "Evaluation" section importing the static numbers from
  `docs/evaluation_report.md` as a small manually-maintained table (Power BI has no
  clean way to run the ground-truth evaluation live — same reasoning as the Streamlit
  app, which renders the static report rather than re-running `evaluate.py` per page load)

### Page 4 — Investigation Operations
- KPI cards: Total/Open/Closed Tickets, Critical Cases, SLA Breach Rate, Avg
  Resolution Hours
- Histogram: priority score distribution, colored by severity
- Bar chart: investigator workload
- Table: filterable ticket queue (status, severity slicers) — Power BI is read-only
  here; the case-action workflow (status updates) stays a Streamlit-only feature,
  since Power BI reports don't write back to the source database

### Page 5 — Seller 360
- Seller slicer (single-select, searchable)
- Card visuals: Health Score, Segment/Tenure, Category, Open Cases
- Line chart: health score history
- Line chart: key metric trends (defect/late-shipment/return rate)
- Table: anomaly timeline
- Table: investigation history
- Table: peer comparison (latest day)

## What Power BI would NOT replicate

The Streamlit app's write-back capability (updating a ticket's status/root-cause/
resolution from the Investigation Operations tab) has no Power BI equivalent — Power
BI reports are read-only against their data source. If write-back were required in a
Power BI context, it would need a separate Power App or a custom connector, which is
out of scope for this spec.
