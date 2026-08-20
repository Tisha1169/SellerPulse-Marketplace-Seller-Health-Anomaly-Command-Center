"""
Simulates an investigator team working the queue: assignment, status progression,
root-cause categorization, and resolution — so the dashboard and Streamlit console
have realistic historical case data instead of an empty queue.

This is a SIMULATION, same spirit as the rest of the ground-truth-labeled data:
it does not claim to represent real investigator behavior, only to produce
plausible, internally-consistent case data for demonstration. Root-cause
categories are weighted per anomaly_type based on which category that anomaly
type most plausibly reflects (e.g. Late_Shipment_Spike -> mostly Logistics).

Status logic: how far a ticket has progressed depends on how much time has
elapsed since detected_date relative to its SLA — tickets detected long enough
ago have had time to reach a terminal state (Resolved/False_Positive/Escalated);
recent tickets are still New/Investigating/Action_Required. This keeps the
timeline internally consistent instead of assigning random statuses regardless
of age.
"""
import numpy as np
import pandas as pd

from anomaly_engine.db import get_engine
from data_generator import config as cfg

rng = np.random.default_rng(cfg.RANDOM_SEED + 6)

INVESTIGATORS = [
    "A. Patel", "J. Kim", "M. Osei", "R. Fernandez", "S. Chen",
    "T. Novak", "L. Okafor", "D. Suresh",
]

ROOT_CAUSE_WEIGHTS = {
    "Late_Shipment_Spike": {"Logistics": 0.70, "Inventory": 0.20, "Data_Quality": 0.10},
    "Defect_Rate_Rise": {"Product_Quality": 0.70, "Seller_Behavior": 0.20, "Data_Quality": 0.10},
    "Return_Rate_Spike": {"Product_Quality": 0.50, "Logistics": 0.20, "Seller_Behavior": 0.20, "Data_Quality": 0.10},
    "Review_Velocity_Spike": {"Review_Anomaly": 0.80, "Seller_Behavior": 0.20},
    "Rating_Manipulation": {"Review_Anomaly": 0.90, "Seller_Behavior": 0.10},
    "Price_Anomaly": {"Pricing": 0.80, "Seller_Behavior": 0.20},
    "Order_Volume_Shock": {"Inventory": 0.40, "Seller_Behavior": 0.30, "Data_Quality": 0.30},
    "Multi_Metric_Deterioration": {"Seller_Behavior": 0.40, "Product_Quality": 0.30, "Logistics": 0.20, "Data_Quality": 0.10},
}

FALSE_POSITIVE_RATE = 0.30
ESCALATED_RATE = 0.12
RESOLUTION_NOTES = {
    "Resolved": "Root cause confirmed and corrective action taken with the seller; metrics trending back to baseline.",
    "False_Positive": "Investigated — deviation traced to normal seasonal/promotional variance, not a genuine seller quality issue.",
    "Escalated": "Pattern consistent with repeated/systemic behavior; escalated to seller account management for policy review.",
}


def _sample_root_cause(anomaly_type: str) -> str:
    weights = ROOT_CAUSE_WEIGHTS.get(anomaly_type, {"Data_Quality": 1.0})
    return rng.choice(list(weights.keys()), p=list(weights.values()))


def simulate(tickets: pd.DataFrame) -> pd.DataFrame:
    tickets = tickets.copy()
    now = pd.Timestamp(cfg.SIMULATION_END_DATE)

    tickets["detected_date"] = pd.to_datetime(tickets["detected_date"])
    days_open_if_untouched = (now - tickets["detected_date"]).dt.days

    tickets["assigned_investigator"] = rng.choice(INVESTIGATORS, size=len(tickets))

    # resolution offset: lognormal centered so most resolve within ~0.6-0.9x SLA,
    # a meaningful tail runs over SLA (that's what produces breaches)
    resolution_hours = rng.lognormal(mean=np.log(tickets["sla_hours"] * 0.65 + 1), sigma=0.5)
    tickets["_resolution_offset_days"] = resolution_hours / 24

    is_terminal = tickets["_resolution_offset_days"] <= days_open_if_untouched
    tickets["status"] = "New"

    # among tickets old enough to have reached a terminal state, split by outcome
    terminal_idx = tickets[is_terminal].index
    outcome_roll = rng.random(len(terminal_idx))
    outcomes = np.where(
        outcome_roll < FALSE_POSITIVE_RATE, "False_Positive",
        np.where(outcome_roll < FALSE_POSITIVE_RATE + ESCALATED_RATE, "Escalated", "Resolved"),
    )
    tickets.loc[terminal_idx, "status"] = outcomes

    # non-terminal tickets: still in progress, status depends on how far along
    in_progress_idx = tickets[~is_terminal].index
    progress_frac = (days_open_if_untouched.loc[in_progress_idx] / tickets.loc[in_progress_idx, "_resolution_offset_days"].clip(lower=0.1))
    tickets.loc[in_progress_idx, "status"] = np.select(
        [progress_frac < 0.15, progress_frac < 0.6],
        ["New", "Investigating"],
        default="Action_Required",
    )

    tickets["root_cause_category"] = None
    closed_mask = tickets["status"].isin(["Resolved", "False_Positive", "Escalated"])
    tickets.loc[closed_mask, "root_cause_category"] = tickets.loc[closed_mask, "anomaly_type"].apply(_sample_root_cause)
    # False_Positive tickets skew toward Data_Quality as the "root cause" of the false alarm itself
    fp_mask = tickets["status"] == "False_Positive"
    tickets.loc[fp_mask, "root_cause_category"] = np.where(rng.random(fp_mask.sum()) < 0.6, "Data_Quality", tickets.loc[fp_mask, "root_cause_category"])

    investigating_mask = tickets["status"].isin(["Investigating", "Action_Required"])
    tickets.loc[investigating_mask, "root_cause_category"] = None

    tickets["resolution"] = None
    tickets["notes"] = None
    tickets.loc[closed_mask, "resolution"] = tickets.loc[closed_mask, "status"].map(RESOLUTION_NOTES)
    tickets.loc[investigating_mask, "notes"] = "Under review — pulling seller history and peer-cohort comparison."

    tickets["resolved_at"] = pd.NaT
    tickets.loc[closed_mask, "resolved_at"] = tickets.loc[closed_mask, "detected_date"] + pd.to_timedelta(
        tickets.loc[closed_mask, "_resolution_offset_days"], unit="D"
    )
    # clamp to not resolve in the future relative to simulation "now"
    tickets.loc[closed_mask, "resolved_at"] = tickets.loc[closed_mask, "resolved_at"].clip(upper=now)

    return tickets.drop(columns="_resolution_offset_days")


def write_back(tickets: pd.DataFrame):
    engine = get_engine()
    with engine.begin() as conn:
        for _, row in tickets.iterrows():
            conn.exec_driver_sql(
                """
                UPDATE core.investigation_tickets
                SET status = %(status)s, assigned_investigator = %(assigned_investigator)s,
                    root_cause_category = %(root_cause_category)s, notes = %(notes)s,
                    resolution = %(resolution)s, resolved_at = %(resolved_at)s, updated_at = now()
                WHERE case_id = %(case_id)s
                """,
                {
                    "status": row["status"],
                    "assigned_investigator": row["assigned_investigator"],
                    "root_cause_category": row["root_cause_category"],
                    "notes": row["notes"],
                    "resolution": row["resolution"],
                    "resolved_at": None if pd.isna(row["resolved_at"]) else row["resolved_at"].to_pydatetime(),
                    "case_id": int(row["case_id"]),
                },
            )
    print(f"Updated {len(tickets):,} tickets with simulated investigator actions")


if __name__ == "__main__":
    engine = get_engine()
    tickets = pd.read_sql(
        """
        SELECT t.*, f.anomaly_type
        FROM core.investigation_tickets t
        JOIN core.fact_anomaly_flags f ON f.flag_id = t.primary_flag_id
        """,
        engine, parse_dates=["detected_date"],
    )
    if tickets.empty:
        print("No tickets found — run investigation.queue_builder first.")
    else:
        simulated = simulate(tickets)
        print(simulated["status"].value_counts())
        write_back(simulated)
