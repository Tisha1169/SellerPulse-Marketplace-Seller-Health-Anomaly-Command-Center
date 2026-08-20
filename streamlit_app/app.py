"""
SellerPulse Investigation Console — a lightweight internal tool for an
operations investigator to triage the queue and act on cases.

Two tabs:
  1. Investigation Queue — sortable/filterable open tickets, update status /
     root cause / resolve inline.
  2. Seller Drill-Down — health score history, KPI trend, anomaly timeline,
     and peer-cohort comparison for one seller.

Run with: streamlit run streamlit_app/app.py
"""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from anomaly_engine.db import get_engine  # noqa: E402

st.set_page_config(page_title="SellerPulse Investigation Console", layout="wide")

STATUS_OPTIONS = ["New", "Investigating", "Action_Required", "Resolved", "False_Positive", "Escalated"]
ROOT_CAUSE_OPTIONS = [None, "Logistics", "Inventory", "Pricing", "Product_Quality", "Seller_Behavior", "Review_Anomaly", "Data_Quality"]


@st.cache_resource
def engine():
    return get_engine()


def run_query(sql: str, params: dict = None) -> pd.DataFrame:
    return pd.read_sql(sql, engine(), params=params or {})


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


st.title("SellerPulse — Investigation Console")
st.caption("Internal tool for triaging flagged sellers and working investigation cases.")

tab_queue, tab_drilldown = st.tabs(["📋 Investigation Queue", "🔍 Seller Drill-Down"])

with tab_queue:
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
            st.rerun()
    else:
        st.write("No cases match the current filters.")

with tab_drilldown:
    sellers = run_query("SELECT seller_id, seller_name FROM core.dim_seller ORDER BY seller_name")
    seller_label = st.selectbox(
        "Select a seller", sellers["seller_id"],
        format_func=lambda sid: f"{sellers.loc[sellers.seller_id == sid, 'seller_name'].values[0]} (#{sid})",
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
    seller_info = run_query(
        "SELECT * FROM core.dim_seller WHERE seller_id = %(sid)s", {"sid": int(seller_label)}
    ).iloc[0]

    latest_health = health_hist.iloc[-1] if not health_hist.empty else None
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Health Score", f"{latest_health['health_score']:.1f}" if latest_health is not None else "n/a",
               help=f"Tier: {latest_health['health_tier'] if latest_health is not None else 'n/a'}")
    m2.metric("Segment / Tenure", f"{seller_info['seller_segment']} / {seller_info['tenure_cohort']}")
    m3.metric("Category", seller_info["primary_category"])
    m4.metric("Open cases", int((run_query(
        "SELECT count(*) AS n FROM core.investigation_tickets WHERE seller_id = %(sid)s AND status NOT IN ('Resolved','False_Positive')",
        {"sid": int(seller_label)},
    ))["n"].iloc[0]))

    st.subheader("Health score history")
    if not health_hist.empty:
        st.line_chart(health_hist.set_index("score_date")["health_score"])

    st.subheader("Key metric trends")
    if not metrics_hist.empty:
        mc1, mc2 = st.columns(2)
        with mc1:
            st.line_chart(metrics_hist.set_index("metric_date")[["defect_rate", "late_shipment_rate", "return_rate"]])
        with mc2:
            st.line_chart(metrics_hist.set_index("metric_date")[["order_volume"]])

    st.subheader("Anomaly timeline")
    if seller_flags.empty:
        st.write("No Ensemble-level anomalies flagged for this seller.")
    else:
        st.dataframe(seller_flags, width="stretch", hide_index=True)

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
