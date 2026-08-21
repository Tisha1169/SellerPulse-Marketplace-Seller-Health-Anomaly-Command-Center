-- Tiny summary table (one row) holding the raw volume counts the Executive
-- Overview KPI strip needs (total orders/shipments/returns/reviews).
--
-- Why this exists: the dashboard only ever needs COUNT(*) from fact_orders,
-- fact_shipments, fact_returns, and fact_reviews — it never reads a single row
-- from them. Those four tables are ~1.07GB combined at this project's scale.
-- Querying a live count() against them works fine locally, but a cloud-hosted
-- read-only demo has no reason to ship ~1.07GB of order-line-level data just to
-- answer four count questions. This table is computed once by the pipeline and
-- is what the deployed app actually queries — see docs/deployment.md.
CREATE TABLE IF NOT EXISTS core.dataset_summary (
    metric_name   TEXT PRIMARY KEY,
    metric_value  BIGINT NOT NULL,
    computed_at   TIMESTAMP NOT NULL DEFAULT now()
);

COMMENT ON TABLE core.dataset_summary IS
'One row per named summary metric (total_orders, total_shipments, etc). Populated by pipeline/populate_dataset_summary.py after each data load. Exists so the Streamlit app never needs to query the full raw fact tables just for a headline count.';
