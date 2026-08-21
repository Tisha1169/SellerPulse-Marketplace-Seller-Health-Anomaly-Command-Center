"""
SellerPulse — Marketplace Seller Health & Anomaly Command Center.

Five tabs, all reading directly from the same PostgreSQL analytics tables the
rest of the project (anomaly_engine/, scoring/, investigation/) writes to — no
metric here is computed differently than it is in the underlying pipeline.

  1. Executive Overview       marketplace-wide KPIs, health tier mix, anomaly
                               trend, health score distribution
  2. Seller Risk Intelligence ranked risky sellers, anomaly frequency, peer-
                               cohort deviation
  3. Anomaly Intelligence     detection trend/type/method breakdown + the
                               project's own ground-truth evaluation report
  4. Investigation Operations ticket ops KPIs + the original filterable queue
                               and case-action workflow
  5. Seller 360                one-seller deep dive: health history, KPI
                               trends, anomaly timeline, peer comparison,
                               investigation history

Run with: streamlit run streamlit_app/app.py
"""
import os
import sys

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from anomaly_engine.db import get_engine  # noqa: E402

st.set_page_config(page_title="SellerPulse — Command Center", layout="wide")

STATUS_OPTIONS = ["New", "Investigating", "Action_Required", "Resolved", "False_Positive", "Escalated"]
ROOT_CAUSE_OPTIONS = [None, "Logistics", "Inventory", "Pricing", "Product_Quality", "Seller_Behavior", "Review_Anomaly", "Data_Quality"]
HEALTH_TIER_ORDER = ["Healthy", "Watch", "At_Risk", "Critical"]
HEALTH_TIER_COLORS = {"Healthy": "#2E7D32", "Watch": "#F9A825", "At_Risk": "#EF6C00", "Critical": "#C62828"}
METHODS = ["ZScore", "IQR", "CUSUM", "IsolationForest", "Ensemble"]
EVAL_REPORT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "evaluation_report.md")


@st.cache_resource
def engine():
    return get_engine()


def _check_database_connection():
    """
    Fails loudly but cleanly instead of letting every query on the page throw
    its own raw SQLAlchemy traceback. The most common deployment failure mode
    is a missing/wrong DATABASE_URL secret on Streamlit Community Cloud — this
    turns that into one readable message instead of a wall of stack traces
    from five different tabs, and never echoes the connection string itself
    (which would leak credentials into the rendered page).
    """
    try:
        with engine().connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:
        # Only the exception TYPE is shown, never str(exc) — some drivers
        # (psycopg2 included) embed the DSN, host, or even the password in
        # their error text, and this message renders directly on the page.
        st.error(
            "**Can't connect to the database.**\n\n"
            "This app needs `DATABASE_URL` set — locally via `.env` "
            "(`POSTGRES_*` variables) or `.streamlit/secrets.toml`, or on "
            "Streamlit Community Cloud via the app's **Secrets** panel. "
            "See `docs/deployment.md` for exact setup steps.\n\n"
            f"Error type: `{type(exc).__name__}` (check server logs for the full trace)."
        )
        st.stop()


_check_database_connection()


def run_query(sql: str, params: dict = None) -> pd.DataFrame:
    return pd.read_sql(sql, engine(), params=params or {})


@st.cache_data(ttl=300)
def cached_query(sql: str, params: dict = None) -> pd.DataFrame:
    """Read-only aggregate queries (Overview / Risk / Anomaly tabs) are cached
    for 5 minutes — they don't need to reflect a ticket update the instant it
    happens. The Investigation Operations tab's own queue query stays
    uncached (via run_query) so acting on a case shows up immediately."""
    return run_query(sql, params)


def update_ticket(case_id: int, status: str, root_cause: str, notes: str, resolution: str):
    resolved_at_sql = "now()" if status in ("Resolved", "False_Positive", "Escalated") else "NULL"
    with engine().begin() as conn:
        conn.exec_driver_sql(
            f"""
            UPDATE core.investigation_tickets
            SET status = %(status)s, root_cause_category = %(root_cause)s,
                notes = %(notes)s, resolution = %(resolution)s,
                resolved_at = {resolved_at_sql}, updated_at = now()
            WHERE case_id = %(case_id)s
            """,
            {"status": status, "root_cause": root_cause, "notes": notes, "resolution": resolution, "case_id": case_id},
        )


st.title("SellerPulse — Marketplace Seller Health & Anomaly Command Center")
st.caption(
    "Internal-tooling-style system for detecting deteriorating third-party marketplace sellers early, "
    "prioritizing investigations, and quantifying the operational impact of early detection."
)

with st.expander("ℹ️ About this project — read in 60-90 seconds", expanded=True):
    st.markdown(
        """
**Problem this solves:** marketplaces run thousands of third-party sellers whose operational quality
(defects, late shipments, returns, fake reviews) can quietly deteriorate before it ever shows up as a
customer complaint. This system monitors that continuously and surfaces it early.

**Data:** a synthetic marketplace with realistic (non-uniform) distributions — 2,000 sellers, 20,000
products, 3.4M orders/shipments, 159K returns, 398K reviews — with 160 deliberately injected, labeled
anomaly episodes so detection accuracy can be honestly measured, not just eyeballed.

**How anomaly detection works:** each seller's daily metrics are compared against both its own 28-day
rolling history and its peer cohort (same tenure × category × size segment). Four independent detection
methods (z-score, IQR, CUSUM drift detection, Isolation Forest) vote — a flag only becomes an actionable
"Ensemble" case if ≥2 methods agree AND the signal persists across 2+ days, a fix added after evaluation
surfaced a real multiple-testing problem (see the **Anomaly Intelligence** tab).

**How risk is scored:** a 0-100 **Seller Health Score** (a *state* — how healthy is this seller right now)
is kept deliberately separate from an **Investigation Priority Score** (a *queue-ranking* metric per flag,
combining severity, financial exposure, customer impact, and detection confidence) — a stable-but-mediocre
seller shouldn't outrank one with a fresh Critical anomaly today, or vice versa.

**What this supports:** prioritizing a finite investigation team's time, tracking SLA compliance,
identifying category-level risk concentration, and a transparent (assumptions-stated) estimate of what
earlier detection would be worth. Full methodology: [`docs/architecture.md`](https://github.com/Tisha1169/SellerPulse-Marketplace-Seller-Health-Anomaly-Command-Center/blob/main/docs/architecture.md).
        """
    )

with st.expander("📖 Metric definitions"):
    st.markdown(
        """
| Term | Definition |
|---|---|
| **Seller Health Score** | 0-100, weighted composite of defect rate, late shipment rate, return rate, cancellation rate, review signal, and recent anomaly penalty. A *state* metric — how healthy a seller is right now. |
| **Health Tier** | Healthy (≥80) / Watch (≥60) / At_Risk (≥40) / Critical (<40), derived from Health Score. |
| **Investigation Priority Score** | 0-100, per anomaly flag — combines severity, trailing-30-day GMV exposure, trailing-30-day order volume, and detection-method agreement count. A *queue-ranking* metric — which case to open first, independent of the seller's overall health state. |
| **Severity** | Low/Medium/High/Critical, from the flag's combined statistical anomaly score. Only High/Critical flags open an investigation ticket. |
| **Ensemble** | A flag promoted to "actionable" because ≥2 of 4 independent detection methods agree AND the signal persists across 2+ distinct days — see the Anomaly Intelligence tab for why the persistence rule exists. |
| **SLA** | Severity-driven response deadline (Critical=24h, High=72h, Medium=120h, Low=240h) set when a ticket is created. |
| **Peer cohort** | Sellers sharing the same tenure cohort × primary category × size segment — the baseline a seller is compared against besides its own history. |
        """
    )

tab_overview, tab_risk, tab_anomaly, tab_investigate, tab_360 = st.tabs(
    ["🏠 Executive Overview", "⚠️ Seller Risk Intelligence", "🔍 Anomaly Intelligence",
     "📋 Investigation Operations", "👤 Seller 360"]
)

# ============================================================
# TAB 1 — Executive Overview
# ============================================================
with tab_overview:
    # Reads core.dataset_summary (a tiny precomputed table) rather than running
    # count(*) against fact_orders/fact_shipments/fact_returns/fact_reviews —
    # those four raw fact tables are ~1.07GB combined and the dashboard never
    # reads a single row from them, only these headline counts. See
    # database/ddl/05_dataset_summary.sql and docs/deployment.md.
    summary_rows = cached_query("SELECT metric_name, metric_value FROM core.dataset_summary")
    summary = summary_rows.set_index("metric_name")["metric_value"].to_dict()
    counts = {
        "total_sellers": summary.get("total_sellers", 0),
        "total_orders": summary.get("total_orders", 0),
        "total_shipments": summary.get("total_shipments", 0),
        "total_returns": summary.get("total_returns", 0),
        "total_reviews": summary.get("total_reviews", 0),
    }

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Sellers", f"{counts['total_sellers']:,}")
    c2.metric("Total Orders", f"{counts['total_orders']:,}")
    c3.metric("Total Shipments", f"{counts['total_shipments']:,}")
    c4.metric("Total Returns", f"{counts['total_returns']:,}")
    c5.metric("Total Reviews", f"{counts['total_reviews']:,}")

    st.divider()

    tier_counts = cached_query(
        """
        SELECT health_tier, count(*) AS n
        FROM core.seller_health_score
        WHERE score_date = (SELECT max(score_date) FROM core.seller_health_score)
        GROUP BY health_tier
        """
    )
    tier_map = tier_counts.set_index("health_tier")["n"].to_dict()

    ops = cached_query(
        """
        SELECT
          count(*) FILTER (WHERE status NOT IN ('Resolved','False_Positive')) AS active_investigations,
          count(*) AS total_tickets,
          count(*) FILTER (WHERE is_sla_breached) AS sla_breaches
        FROM core.investigation_tickets
        """
    ).iloc[0]

    d1, d2, d3, d4, d5, d6 = st.columns(6)
    for col, tier in zip((d1, d2, d3, d4), HEALTH_TIER_ORDER):
        col.metric(tier.replace("_", " "), f"{tier_map.get(tier, 0):,}")
    d5.metric("Active Investigations", f"{int(ops['active_investigations']):,}")
    breach_pct = (ops["sla_breaches"] / ops["total_tickets"] * 100) if ops["total_tickets"] else 0
    d6.metric("SLA Breaches", f"{int(ops['sla_breaches']):,}", help=f"{breach_pct:.1f}% of all tickets")

    st.divider()

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.subheader("Seller health tier mix")
        tier_df = pd.DataFrame({"health_tier": HEALTH_TIER_ORDER})
        tier_df["n"] = tier_df["health_tier"].map(tier_map).fillna(0)
        fig = px.bar(
            tier_df, x="health_tier", y="n", color="health_tier",
            color_discrete_map=HEALTH_TIER_COLORS, category_orders={"health_tier": HEALTH_TIER_ORDER},
            labels={"n": "Sellers", "health_tier": "Health Tier"},
        )
        fig.update_layout(showlegend=False, height=350)
        st.plotly_chart(fig, width="stretch")

    with chart_col2:
        st.subheader("Seller Health Score distribution")
        dist = cached_query(
            "SELECT health_score FROM core.seller_health_score "
            "WHERE score_date = (SELECT max(score_date) FROM core.seller_health_score)"
        )
        fig = px.histogram(dist, x="health_score", nbins=40, labels={"health_score": "Health Score"})
        fig.update_layout(height=350)
        st.plotly_chart(fig, width="stretch")

    st.subheader("Anomaly trend (Ensemble flags per day)")
    trend = cached_query(
        "SELECT flag_date, count(*) AS n FROM core.fact_anomaly_flags "
        "WHERE method = 'Ensemble' GROUP BY flag_date ORDER BY flag_date"
    )
    if not trend.empty:
        fig = px.line(trend, x="flag_date", y="n", labels={"flag_date": "Date", "n": "Ensemble flags"})
        fig.update_layout(height=350)
        st.plotly_chart(fig, width="stretch")

# ============================================================
# TAB 2 — Seller Risk Intelligence
# ============================================================
with tab_risk:
    st.subheader("Top risky sellers")
    st.caption(
        "Ranked by current Health Score (ascending — worst first). Open Priority Score is the highest "
        "priority_score among that seller's currently-open investigation tickets, if any."
    )
    top_n = st.slider("Number of sellers to show", 10, 100, 30, step=10)

    risky = cached_query(
        """
        SELECT h.seller_id, s.seller_name, s.seller_segment, s.primary_category,
               h.health_score, h.health_tier,
               m.defect_rate, m.late_shipment_rate, m.return_rate, m.avg_rating,
               coalesce(a.anomaly_count, 0) AS anomaly_count,
               t.max_priority AS open_priority_score
        FROM core.seller_health_score h
        JOIN core.dim_seller s ON s.seller_id = h.seller_id
        LEFT JOIN core.fact_seller_daily_metrics m ON m.seller_id = h.seller_id AND m.metric_date = h.score_date
        LEFT JOIN (
            SELECT seller_id, count(*) AS anomaly_count FROM core.fact_anomaly_flags
            WHERE method = 'Ensemble' GROUP BY seller_id
        ) a ON a.seller_id = h.seller_id
        LEFT JOIN (
            SELECT seller_id, max(priority_score) AS max_priority FROM core.investigation_tickets
            WHERE status NOT IN ('Resolved','False_Positive') GROUP BY seller_id
        ) t ON t.seller_id = h.seller_id
        WHERE h.score_date = (SELECT max(score_date) FROM core.seller_health_score)
        ORDER BY h.health_score ASC
        LIMIT %(n)s
        """,
        {"n": top_n},
    )
    st.dataframe(
        risky[["seller_id", "seller_name", "seller_segment", "primary_category", "health_score", "health_tier",
               "defect_rate", "late_shipment_rate", "return_rate", "avg_rating", "anomaly_count", "open_priority_score"]],
        width="stretch", hide_index=True,
    )

    rc1, rc2 = st.columns(2)
    with rc1:
        st.subheader("Anomaly frequency — top 15 by flag count")
        freq = risky.nlargest(15, "anomaly_count")[["seller_name", "anomaly_count"]]
        if freq["anomaly_count"].sum() > 0:
            fig = px.bar(freq.sort_values("anomaly_count"), x="anomaly_count", y="seller_name", orientation="h",
                         labels={"anomaly_count": "Ensemble flags (all-time)", "seller_name": ""})
            fig.update_layout(height=450)
            st.plotly_chart(fig, width="stretch")
        else:
            st.write("No anomaly flags among the currently shown sellers.")

    with rc2:
        st.subheader("Peer-cohort deviation (trailing 30 days)")
        st.caption("Average |z-score| vs. same tenure × category × segment peers, per metric — higher = more unusual.")
        seller_ids = risky["seller_id"].tolist()
        peer = cached_query(
            """
            SELECT seller_id, metric_name, avg(abs(cohort_zscore)) AS avg_abs_z
            FROM core.seller_metric_cohort_baseline
            WHERE seller_id = ANY(%(ids)s)
              AND metric_date >= (SELECT max(metric_date) - 30 FROM core.fact_seller_daily_metrics)
              AND cohort_zscore IS NOT NULL
            GROUP BY seller_id, metric_name
            """,
            {"ids": seller_ids},
        )
        if not peer.empty:
            name_map = risky.set_index("seller_id")["seller_name"].to_dict()
            peer["seller_name"] = peer["seller_id"].map(name_map)
            pivot = peer.pivot_table(index="seller_name", columns="metric_name", values="avg_abs_z")
            # cap the heatmap to a readable number of rows — same top-N slider drives this
            pivot = pivot.loc[risky["seller_name"].tolist()[:min(20, len(pivot))]]
            fig = px.imshow(pivot, aspect="auto", color_continuous_scale="Reds", labels={"color": "avg |z|"})
            fig.update_layout(height=450)
            st.plotly_chart(fig, width="stretch")
        else:
            st.write("No peer-cohort baseline data for the currently shown sellers.")

# ============================================================
# TAB 3 — Anomaly Intelligence
# ============================================================
with tab_anomaly:
    st.subheader("Anomaly trend by type (weekly, Ensemble flags)")
    by_type = cached_query(
        """
        SELECT date_trunc('week', flag_date)::date AS week, anomaly_type, count(*) AS n
        FROM core.fact_anomaly_flags
        WHERE method = 'Ensemble'
        GROUP BY week, anomaly_type
        ORDER BY week
        """
    )
    if not by_type.empty:
        fig = px.area(by_type, x="week", y="n", color="anomaly_type",
                       labels={"week": "Week", "n": "Ensemble flags", "anomaly_type": "Anomaly Type"})
        fig.update_layout(height=400)
        st.plotly_chart(fig, width="stretch")

    ac1, ac2 = st.columns(2)
    with ac1:
        st.subheader("Anomaly type breakdown")
        type_totals = cached_query(
            "SELECT anomaly_type, count(*) AS n FROM core.fact_anomaly_flags "
            "WHERE method = 'Ensemble' GROUP BY anomaly_type ORDER BY n DESC"
        )
        fig = px.bar(type_totals, x="n", y="anomaly_type", orientation="h",
                     labels={"n": "Ensemble flags", "anomaly_type": ""})
        fig.update_layout(height=350)
        st.plotly_chart(fig, width="stretch")

    with ac2:
        st.subheader("Detection method comparison (raw flag volume)")
        st.caption("Every method's individual flags — not just the ones promoted to Ensemble. Shows why voting/persistence is needed.")
        method_totals = cached_query(
            "SELECT method, count(*) AS n FROM core.fact_anomaly_flags GROUP BY method"
        )
        method_totals["method"] = pd.Categorical(method_totals["method"], categories=METHODS, ordered=True)
        method_totals = method_totals.sort_values("method")
        fig = px.bar(method_totals, x="method", y="n", labels={"n": "Total flags", "method": "Method"})
        fig.update_layout(height=350)
        st.plotly_chart(fig, width="stretch")

    st.divider()
    st.subheader("📊 Ground-truth evaluation (synthetic data only)")
    st.warning(
        "The numbers below measure detection accuracy against **deliberately injected, labeled synthetic "
        "anomalies** — they are NOT a claim about real-world marketplace performance. See "
        "`anomaly_engine/evaluate.py` and `data_generator/inject_anomalies.py` for methodology."
    )
    if os.path.exists(EVAL_REPORT_PATH):
        with open(EVAL_REPORT_PATH) as f:
            st.markdown(f.read())
    else:
        st.write("Evaluation report not found — run `python -m anomaly_engine.evaluate` to generate it.")

# ============================================================
# TAB 4 — Investigation Operations
# ============================================================
with tab_investigate:
    ops_kpi = run_query(
        """
        SELECT
          count(*) AS total_tickets,
          count(*) FILTER (WHERE status NOT IN ('Resolved','False_Positive','Escalated')) AS open_tickets,
          count(*) FILTER (WHERE status IN ('Resolved','False_Positive','Escalated')) AS closed_tickets,
          count(*) FILTER (WHERE severity = 'Critical') AS critical_tickets,
          count(*) FILTER (WHERE is_sla_breached) AS sla_breaches,
          round(100.0 * count(*) FILTER (WHERE is_sla_breached) / nullif(count(*), 0), 1) AS sla_breach_pct,
          round(avg(EXTRACT(EPOCH FROM (resolved_at - detected_date::timestamp)) / 3600)
                FILTER (WHERE resolved_at IS NOT NULL), 1) AS avg_resolution_hours
        FROM core.investigation_tickets
        """
    ).iloc[0]

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total Tickets", f"{int(ops_kpi['total_tickets']):,}")
    k2.metric("Open Tickets", f"{int(ops_kpi['open_tickets']):,}")
    k3.metric("Closed Tickets", f"{int(ops_kpi['closed_tickets']):,}")
    k4.metric("Critical Cases", f"{int(ops_kpi['critical_tickets']):,}")
    k5.metric("SLA Breach Rate", f"{ops_kpi['sla_breach_pct'] or 0:.1f}%")
    k6.metric("Avg Resolution Time", f"{ops_kpi['avg_resolution_hours'] or 0:.0f}h")

    wc1, wc2 = st.columns(2)
    with wc1:
        st.subheader("Priority distribution (open tickets)")
        open_tix = run_query(
            "SELECT priority_score, severity FROM core.investigation_tickets "
            "WHERE status NOT IN ('Resolved','False_Positive','Escalated')"
        )
        if not open_tix.empty:
            fig = px.histogram(open_tix, x="priority_score", color="severity", nbins=30,
                                labels={"priority_score": "Priority Score"})
            fig.update_layout(height=320)
            st.plotly_chart(fig, width="stretch")
    with wc2:
        st.subheader("Investigator workload")
        workload = run_query(
            "SELECT assigned_investigator, count(*) AS n FROM core.investigation_tickets "
            "WHERE assigned_investigator IS NOT NULL GROUP BY assigned_investigator ORDER BY n DESC"
        )
        if not workload.empty:
            fig = px.bar(workload, x="n", y="assigned_investigator", orientation="h",
                         labels={"n": "Cases", "assigned_investigator": ""})
            fig.update_layout(height=320)
            st.plotly_chart(fig, width="stretch")

    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1:
        status_filter = st.multiselect("Status", STATUS_OPTIONS, default=["New", "Investigating", "Action_Required"])
    with col2:
        severity_filter = st.multiselect("Severity", ["Critical", "High"], default=["Critical", "High"])
    with col3:
        sort_by = st.selectbox("Sort by", ["priority_score", "sla_deadline", "detected_date"], index=0)

    queue = run_query(
        """
        SELECT t.case_id, t.seller_id, s.seller_name, f.anomaly_type, f.affected_metric,
               t.severity, t.priority_score, t.status, t.assigned_investigator,
               t.detected_date, t.sla_deadline, t.is_sla_breached, f.explanation
        FROM core.investigation_tickets t
        JOIN core.fact_anomaly_flags f ON f.flag_id = t.primary_flag_id
        JOIN core.dim_seller s ON s.seller_id = t.seller_id
        WHERE t.status = ANY(%(statuses)s) AND t.severity = ANY(%(severities)s)
        ORDER BY {sort} DESC
        """.format(sort=sort_by),
        {"statuses": status_filter or STATUS_OPTIONS, "severities": severity_filter or ["Critical", "High"]},
    )

    st.write(f"**{len(queue)} cases**")
    st.dataframe(
        queue[["case_id", "seller_id", "seller_name", "anomaly_type", "affected_metric", "severity",
               "priority_score", "status", "assigned_investigator", "detected_date", "sla_deadline", "is_sla_breached"]],
        width="stretch", hide_index=True,
    )

    st.subheader("Act on a case")
    if not queue.empty:
        case_id = st.selectbox("Case ID", queue["case_id"].tolist())
        case_row = queue[queue["case_id"] == case_id].iloc[0]
        st.markdown(f"**Seller:** {case_row['seller_name']} (#{case_row['seller_id']}) — **{case_row['anomaly_type']}**")
        st.info(case_row["explanation"])

        c1, c2 = st.columns(2)
        with c1:
            new_status = st.selectbox("Update status", STATUS_OPTIONS, index=STATUS_OPTIONS.index(case_row["status"]))
            root_cause = st.selectbox("Root cause category", ROOT_CAUSE_OPTIONS, format_func=lambda x: x or "(none)")
        with c2:
            notes = st.text_area("Notes", value="")
            resolution = st.text_area("Resolution (if closing)", value="")

        if st.button("Save case update", type="primary"):
            update_ticket(int(case_id), new_status, root_cause, notes, resolution)
            st.success(f"Case #{case_id} updated to {new_status}.")
            st.cache_data.clear()
            st.rerun()
    else:
        st.write("No cases match the current filters.")

# ============================================================
# TAB 5 — Seller 360
# ============================================================
with tab_360:
    sellers = cached_query("SELECT seller_id, seller_name FROM core.dim_seller ORDER BY seller_name")
    seller_label = st.selectbox(
        "Select a seller", sellers["seller_id"],
        format_func=lambda sid: f"{sellers.loc[sellers.seller_id == sid, 'seller_name'].values[0]} (#{sid})",
        key="seller_360_select",
    )

    health_hist = run_query(
        "SELECT score_date, health_score, health_tier FROM core.seller_health_score "
        "WHERE seller_id = %(sid)s ORDER BY score_date",
        {"sid": int(seller_label)},
    )
    metrics_hist = run_query(
        "SELECT metric_date, defect_rate, late_shipment_rate, return_rate, avg_rating, order_volume, gmv "
        "FROM core.fact_seller_daily_metrics WHERE seller_id = %(sid)s ORDER BY metric_date",
        {"sid": int(seller_label)},
    )
    seller_flags = run_query(
        "SELECT flag_date, anomaly_type, affected_metric, method, severity, anomaly_score, explanation "
        "FROM core.fact_anomaly_flags WHERE seller_id = %(sid)s AND method = 'Ensemble' ORDER BY flag_date DESC",
        {"sid": int(seller_label)},
    )
    seller_tickets = run_query(
        "SELECT case_id, detected_date, severity, priority_score, status, assigned_investigator, "
        "root_cause_category, resolution, is_sla_breached "
        "FROM core.investigation_tickets WHERE seller_id = %(sid)s ORDER BY detected_date DESC",
        {"sid": int(seller_label)},
    )
    seller_info = run_query(
        "SELECT * FROM core.dim_seller WHERE seller_id = %(sid)s", {"sid": int(seller_label)}
    ).iloc[0]

    latest_health = health_hist.iloc[-1] if not health_hist.empty else None
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Health Score", f"{latest_health['health_score']:.1f}" if latest_health is not None else "n/a",
               help=f"Tier: {latest_health['health_tier'] if latest_health is not None else 'n/a'}")
    m2.metric("Segment / Tenure", f"{seller_info['seller_segment']} / {seller_info['tenure_cohort']}")
    m3.metric("Category", seller_info["primary_category"])
    open_tickets_n = int((seller_tickets["status"].isin(["Resolved", "False_Positive"]) == False).sum()) if not seller_tickets.empty else 0
    m4.metric("Open cases", open_tickets_n)
    top_priority = seller_tickets.loc[~seller_tickets["status"].isin(["Resolved", "False_Positive"]), "priority_score"].max() if not seller_tickets.empty else None
    m5.metric("Top Investigation Priority", f"{top_priority:.1f}" if pd.notna(top_priority) else "n/a")

    st.subheader("Health score history")
    if not health_hist.empty:
        fig = px.line(health_hist, x="score_date", y="health_score", labels={"score_date": "Date", "health_score": "Health Score"})
        fig.update_layout(height=300)
        st.plotly_chart(fig, width="stretch")

    st.subheader("Key metric trends")
    if not metrics_hist.empty:
        mc1, mc2 = st.columns(2)
        with mc1:
            fig = px.line(metrics_hist, x="metric_date", y=["defect_rate", "late_shipment_rate", "return_rate"],
                          labels={"metric_date": "Date", "value": "Rate"})
            fig.update_layout(height=300)
            st.plotly_chart(fig, width="stretch")
        with mc2:
            fig = px.line(metrics_hist, x="metric_date", y="order_volume", labels={"metric_date": "Date", "order_volume": "Orders"})
            fig.update_layout(height=300)
            st.plotly_chart(fig, width="stretch")

    st.subheader("Anomaly timeline")
    if seller_flags.empty:
        st.write("No Ensemble-level anomalies flagged for this seller.")
    else:
        st.dataframe(seller_flags, width="stretch", hide_index=True)

    st.subheader("Investigation history")
    if seller_tickets.empty:
        st.write("No investigation tickets for this seller.")
    else:
        st.dataframe(seller_tickets, width="stretch", hide_index=True)

    st.subheader("Peer comparison (latest day)")
    peer_comparison = run_query(
        """
        SELECT metric_name, observed_value, cohort_mean, cohort_zscore
        FROM core.seller_metric_cohort_baseline
        WHERE seller_id = %(sid)s AND metric_date = (SELECT max(metric_date) FROM core.fact_seller_daily_metrics)
        ORDER BY metric_name
        """,
        {"sid": int(seller_label)},
    )
    if not peer_comparison.empty:
        st.dataframe(peer_comparison, width="stretch", hide_index=True)
