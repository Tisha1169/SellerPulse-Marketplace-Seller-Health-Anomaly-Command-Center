# Data Dictionary

Full column-level detail lives in the DDL comments (`database/ddl/*.sql`); this is the narrative reference — grain, purpose, and any non-obvious modeling decision per table.

## Dimensions

| Table | Grain | Notes |
|---|---|---|
| `dim_seller` | one row per seller (SCD2-capable) | Peer cohort for baselining = `(tenure_cohort, primary_category, seller_segment)`. |
| `dim_product` | one row per SKU | Every seller guaranteed ≥1 product (see `data_generator/generate_products.py` — a seller with 0 products can never generate an order, so this is enforced, not left to chance). |
| `dim_customer` | one row per customer | `customer_segment` weights order-assignment probability so VIP customers legitimately order more often. |
| `dim_date` | one row per calendar day | Covers a wider window than the order-generation window so tenure/signup dates outside the active data window still resolve. |

## Facts

| Table | Grain | Notes |
|---|---|---|
| `fact_orders` | one order **line item** | **Simplification, documented deliberately**: `order_id == order_line_id` — this project does not model multi-item orders. Real marketplaces do; this keeps the grain unambiguous for a portfolio project. |
| `fact_shipments` | one shipment | One shipment per non-cancelled order line (no shipment consolidation modeled). |
| `fact_returns` | one return event | `is_defect_related` drives `defect_rate` downstream — attributed to the **originating order's `order_date`**, not the return-processing date (see grain note below). |
| `fact_reviews` | one review | Left-skewed rating distribution (most e-commerce reviews are 4-5 stars) by default; `Rating_Manipulation` episodes override this locally. |
| `fact_seller_daily_metrics` | one row per `(seller_id, metric_date)` | The analytical spine — every downstream table reads this, none read the raw facts directly. |
| `fact_anomaly_flags` | one row per `(seller_id, flag_date, anomaly_type, method)` | Append-only audit trail. `method='Ensemble'` rows are the only ones eligible to spawn tickets. |
| `investigation_tickets` | one row per case | A case can bundle multiple same-day flags for one seller via `primary_flag_id` + `related_flag_ids`. |
| `ground_truth_anomalies` | one row per injected episode | **Never** joined into production tables — exists solely for `anomaly_engine/evaluate.py`. |

## A grain decision worth explaining: return/defect rate attribution

`defect_rate`, `return_rate`, and `refund_rate` in `fact_seller_daily_metrics` are computed by joining each return back to its **originating order's `order_date`**, not the date the return was processed (`sql_analytics/seller_daily_metrics.sql`). This was a real bug found during development: the first version grouped returns by `return_date`, which meant a day with few new orders but many returns *processed* that day (from unrelated earlier orders) could show a "defect rate" over 100% — a numerically nonsensical, unbounded ratio between two different cohorts. Attributing the return back to the order's own date makes every rate a valid same-cohort ratio, bounded in [0, 1], and also correctly reflects "how defective were the orders placed on day X" (which is what an operations analyst actually wants to trend) rather than "how many complaints arrived on day X" (a different, noisier question).

## Rolling baseline tables

| Table | Grain | Purpose |
|---|---|---|
| `seller_metric_rolling_baseline` | `(seller_id, metric_date, metric_name)` | Self-baseline: 28-day trailing mean/std, **excluding the current day** (a metric can't be baselined against itself). `self_zscore` is `NULL` until a seller has ≥10 trailing observations. |
| `seller_metric_cohort_baseline` | `(seller_id, metric_date, metric_name)` | Peer-cohort baseline: same-day mean/std across sellers in the same `(tenure_cohort, primary_category, seller_segment)` group. `cohort_zscore` is `NULL` when fewer than 5 peers exist that day. |

Both are unpivoted (long format) across 9-10 metrics so the anomaly engine can treat every metric identically rather than writing per-metric SQL.

## Health score components (`seller_health_score`)

Each `*_component` column is 0-100 (100 = healthy), normalized against a population 95th-percentile ceiling (see `scoring/health_score.py` for the full weighting rationale and the zero-inflation edge case it handles).
