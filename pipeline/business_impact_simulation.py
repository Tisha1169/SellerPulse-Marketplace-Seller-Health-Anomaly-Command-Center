"""
Business impact simulation: "without early detection" vs. "with SellerPulse".

Every number here is SIMULATED and ESTIMATED — labeled as such everywhere it's
surfaced. This is not a claim about real marketplace savings; it's a transparent
model showing what a detection-delay improvement would be worth IF the stated
assumptions held, with every assumption listed so it can be challenged.

Method: for each investigation ticket that maps to a KNOWN injected ground-truth
episode (an inner join, not every resolved ticket — most tickets have no
matching injected episode and simulating "days saved" against a baseline that
never had a real start date would be fabricating a number, not estimating one),
compare the actual detection delay (episode start_date -> ticket detected_date)
against an assumed REACTIVE baseline — the delay a marketplace would see if it
only learned about a deteriorating seller through customer complaints reaching a
threshold, ~10 days (stated explicitly below, not hidden in a constant). The
"orders affected in the gap" is the seller's average daily order volume in the
days just before detection, multiplied by the gap in days.

This deliberately produces a SMALLER, more defensible case count than "all
resolved tickets" would — see docs/business_case_study.md for the resulting
scope note.
"""
import os

import numpy as np
import pandas as pd

from anomaly_engine.db import get_engine

REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "docs", "business_case_study.md")

# ---- Explicit, challengeable assumptions ----
ASSUMED_REACTIVE_DETECTION_DAYS = 10  # industry-convention estimate: time for a
                                       # deteriorating seller to surface via customer
                                       # complaints/support escalation without proactive monitoring
INVESTIGATOR_HOURLY_COST_USD = 45      # loaded cost estimate for an ops investigator
REACTIVE_INVESTIGATION_HOURS = 6        # assumed hours to investigate a complaint-driven case
                                          # (more context-gathering needed vs. a system-flagged case)
PROACTIVE_INVESTIGATION_HOURS = 3        # assumed hours for a system-flagged case (evidence pre-assembled)
DEFECT_COST_PER_AFFECTED_ORDER_USD = 8    # assumed downstream cost per order shipped during an
                                            # undetected defect episode (refund handling, support, goodwill credits)


def simulate() -> dict:
    engine = get_engine()
    tickets = pd.read_sql(
        """
        SELECT t.case_id, t.seller_id, t.detected_date, t.severity, t.status,
               f.anomaly_type
        FROM core.investigation_tickets t
        JOIN core.fact_anomaly_flags f ON f.flag_id = t.primary_flag_id
        WHERE t.status IN ('Resolved', 'Escalated')
        """,
        engine, parse_dates=["detected_date"],
    )
    if tickets.empty:
        return {}

    daily_orders = pd.read_sql(
        "SELECT seller_id, metric_date, order_volume, gmv FROM core.fact_seller_daily_metrics",
        engine, parse_dates=["metric_date"],
    )
    avg_orders = daily_orders.groupby("seller_id")["order_volume"].mean().rename("avg_daily_orders")
    avg_gmv = daily_orders.groupby("seller_id")["gmv"].mean().rename("avg_daily_gmv")

    tickets = tickets.merge(avg_orders, on="seller_id", how="left").merge(avg_gmv, on="seller_id", how="left")

    # INNER join: only tickets that map to a KNOWN injected episode are used —
    # simulating "days saved" for a ticket with no real episode start date would
    # be fabricating a number, not estimating one. This is why n_cases below is
    # much smaller than "all resolved tickets" (~3,100) would suggest.
    n_all_resolved = len(tickets)
    ground_truth = pd.read_sql(
        "SELECT seller_id, anomaly_type, start_date FROM core.ground_truth_anomalies", engine, parse_dates=["start_date"]
    )
    tickets = tickets.merge(ground_truth, on=["seller_id", "anomaly_type"], how="inner")
    tickets = tickets[tickets["detected_date"] >= tickets["start_date"]]
    tickets["actual_detection_delay_days"] = (tickets["detected_date"] - tickets["start_date"]).dt.days.clip(lower=0)

    tickets["reactive_detection_delay_days"] = ASSUMED_REACTIVE_DETECTION_DAYS
    tickets["days_saved"] = (tickets["reactive_detection_delay_days"] - tickets["actual_detection_delay_days"]).clip(lower=0)

    tickets["orders_potentially_affected_in_gap"] = (tickets["days_saved"] * tickets["avg_daily_orders"].fillna(0)).round(0)
    tickets["gmv_exposure_in_gap"] = (tickets["days_saved"] * tickets["avg_daily_gmv"].fillna(0)).round(2)
    tickets["estimated_defect_cost_avoided_usd"] = (
        tickets["orders_potentially_affected_in_gap"] * DEFECT_COST_PER_AFFECTED_ORDER_USD
    ).round(2)

    n_cases = len(tickets)
    total_orders_protected = tickets["orders_potentially_affected_in_gap"].sum()
    total_gmv_exposure_avoided = tickets["gmv_exposure_in_gap"].sum()
    total_defect_cost_avoided = tickets["estimated_defect_cost_avoided_usd"].sum()
    mean_days_saved = tickets["days_saved"].mean()

    investigation_hours_saved = n_cases * (REACTIVE_INVESTIGATION_HOURS - PROACTIVE_INVESTIGATION_HOURS)
    investigation_cost_saved = investigation_hours_saved * INVESTIGATOR_HOURLY_COST_USD

    n_customers_estimate = int(total_orders_protected)  # 1 order ~ 1 customer interaction, conservative proxy

    return {
        "n_cases": n_cases,
        "n_all_resolved_tickets": n_all_resolved,
        "mean_days_saved": round(mean_days_saved, 1),
        "total_orders_protected": int(total_orders_protected),
        "total_customers_protected_estimate": n_customers_estimate,
        "total_gmv_exposure_avoided": round(total_gmv_exposure_avoided, 2),
        "total_defect_cost_avoided_usd": round(total_defect_cost_avoided, 2),
        "investigation_hours_saved": investigation_hours_saved,
        "investigation_cost_saved_usd": round(investigation_cost_saved, 2),
        "tickets_detail": tickets,
    }


def write_report(results: dict):
    if not results:
        print("No resolved/escalated tickets to simulate impact from.")
        return

    lines = [
        "# Business Impact Simulation (SIMULATED / ESTIMATED — not real marketplace savings)\n",
        "**Every number below is a simulation output, not a measured business result.** "
        "It shows what a detection-delay improvement would be worth IF the stated "
        "assumptions held. Assumptions are listed explicitly so each one can be "
        "challenged independently rather than trusting a blended headline number.\n",
        "## Assumptions\n",
        f"- Reactive baseline detection delay (no proactive monitoring): **{ASSUMED_REACTIVE_DETECTION_DAYS} days** "
        "— the assumed time for a deteriorating seller to surface via customer complaints/support escalation.\n",
        f"- Investigator loaded cost: **${INVESTIGATOR_HOURLY_COST_USD}/hour**.\n",
        f"- Reactive (complaint-driven) investigation time: **{REACTIVE_INVESTIGATION_HOURS} hours/case** "
        "(more context-gathering needed — no pre-assembled evidence).\n",
        f"- Proactive (system-flagged) investigation time: **{PROACTIVE_INVESTIGATION_HOURS} hours/case** "
        "(anomaly evidence, baseline comparison, and peer-cohort context already assembled by the system).\n",
        f"- Estimated downstream cost per order shipped during an undetected defect episode: "
        f"**${DEFECT_COST_PER_AFFECTED_ORDER_USD}** (refund handling, support contacts, goodwill credits).\n",
        "## Scope note\n",
        f"This simulation covers **{results['n_cases']:,} cases** out of "
        f"{results['n_all_resolved_tickets']:,} total resolved/escalated investigation tickets — only "
        "the subset that maps to a KNOWN injected ground-truth episode with a real start date. Applying "
        "this framing to every resolved ticket would fabricate a 'days saved' number for tickets that "
        "have no actual episode start date to measure against (most resolved tickets are either false "
        "positives that got closed, or genuine but non-injected variation); restricting to matched "
        "episodes keeps every number below traceable to a specific, known anomaly.\n",
        "## Without Early Detection vs. With SellerPulse\n",
        "| Metric | Value |",
        "|---|---|",
        f"| Cases simulated | {results['n_cases']:,} |",
        f"| Mean detection days saved per case | {results['mean_days_saved']} |",
        f"| Orders potentially protected | {results['total_orders_protected']:,} |",
        f"| Customers potentially protected (proxy: 1 order ≈ 1 customer) | {results['total_customers_protected_estimate']:,} |",
        f"| GMV exposure avoided (estimated) | ${results['total_gmv_exposure_avoided']:,.2f} |",
        f"| Estimated downstream defect cost avoided | ${results['total_defect_cost_avoided_usd']:,.2f} |",
        f"| Investigation hours saved (proactive vs. reactive investigation time) | {results['investigation_hours_saved']:,} |",
        f"| Investigation cost saved (estimated) | ${results['investigation_cost_saved_usd']:,.2f} |",
        "\n## How to read this\n",
        "This simulation deliberately does NOT claim these are real savings — there is no production "
        "baseline to compare against, only a stated assumption about reactive detection delay. Its value "
        "is as a **structured way to reason about the mechanism**: detection speed converts directly into "
        "orders/customers not exposed to a known-bad seller for as long, and pre-assembled evidence "
        "converts directly into less investigator time per case. A real deployment would replace "
        f"`{ASSUMED_REACTIVE_DETECTION_DAYS} days`, `${INVESTIGATOR_HOURLY_COST_USD}/hour`, and the "
        "investigation-hours assumptions with measured historical values before this framing could be "
        "presented as an actual business case.\n",
        "## Why 'days saved' is modest in this run\n",
        f"Mean days saved is only **{results['mean_days_saved']}** against a {ASSUMED_REACTIVE_DETECTION_DAYS}-day "
        "reactive baseline — smaller than a marketing pitch would want. This is a direct, visible "
        "consequence of the precision/recall/speed trade-off documented in "
        "`docs/evaluation_report.md`: the ensemble's persistence requirement (a signal must repeat across "
        "2+ days before promotion) intentionally trades detection speed for fewer false positives, and "
        "mean Ensemble detection delay in the current tuning is ~9.5 days — already close to the assumed "
        "reactive baseline. A looser, faster-firing configuration would show a larger 'days saved' number "
        "here at the cost of the investigation queue being noisier — that trade-off is real and worth "
        "stating plainly rather than picking whichever threshold makes this section look better.\n",
    ]
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write("\n".join(lines))
    print(f"Business impact report written to {REPORT_PATH}")


if __name__ == "__main__":
    results = simulate()
    if results:
        for k, v in results.items():
            if k != "tickets_detail":
                print(f"{k}: {v}")
    write_report(results)
