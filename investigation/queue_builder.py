"""
Builds core.investigation_tickets from Ensemble anomaly flags.

Only High and Critical severity Ensemble flags spawn tickets — Medium/Low
Ensemble flags remain visible in fact_anomaly_flags (the audit trail) but don't
consume investigator time. This threshold is the concrete answer to "not every
anomaly becomes a case": see docs/evaluation_report.md for why raw flag volume
without this gate would overwhelm a real queue.

Bundling: if a seller has multiple qualifying flags on the SAME day, they're
bundled into one case (one ticket per seller per day, not one per flag) via
primary_flag_id (highest priority_score) + related_flag_ids — an investigator
looking at a seller doesn't want five separate tickets for five metrics that
broke on the same day.
"""
import pandas as pd

from anomaly_engine.db import get_engine
from scoring.priority_score import compute_priority_scores

TICKET_SEVERITY_GATE = {"High", "Critical"}


def build_tickets() -> pd.DataFrame:
    priority = compute_priority_scores()
    if priority.empty:
        return priority

    priority = priority[priority["severity"].isin(TICKET_SEVERITY_GATE)].copy()
    if priority.empty:
        return priority

    priority = priority.sort_values("priority_score", ascending=False)

    tickets = []
    for (seller_id, flag_date), grp in priority.groupby(["seller_id", "flag_date"]):
        primary = grp.iloc[0]
        related_ids = grp["flag_id"].tolist()[1:]
        tickets.append(
            {
                "seller_id": seller_id,
                "primary_flag_id": int(primary["flag_id"]),
                "related_flag_ids": related_ids,
                "severity": primary["severity"],
                "priority_score": primary["priority_score"],
                "detected_date": flag_date,
                "sla_hours": int(primary["sla_hours"]),
                "anomaly_type": primary["anomaly_type"],
                "affected_metric": primary["affected_metric"],
                "explanation": primary["explanation"],
            }
        )
    return pd.DataFrame(tickets)


def write_tickets(tickets: pd.DataFrame):
    engine = get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql("TRUNCATE core.investigation_tickets RESTART IDENTITY CASCADE")

    insert_df = tickets.copy()
    insert_df["sla_deadline"] = pd.to_datetime(insert_df["detected_date"]) + pd.to_timedelta(
        insert_df["sla_hours"], unit="h"
    )
    insert_df["status"] = "New"
    insert_df["root_cause_category"] = None
    insert_df["notes"] = None
    insert_df["resolution"] = None
    insert_df["resolved_at"] = None
    insert_df["is_sla_breached"] = False
    insert_df["assigned_investigator"] = None

    cols = [
        "seller_id", "primary_flag_id", "related_flag_ids", "severity", "priority_score",
        "detected_date", "sla_hours", "sla_deadline", "status", "assigned_investigator",
        "root_cause_category", "notes", "resolution", "resolved_at", "is_sla_breached",
    ]
    insert_df[cols].to_sql(
        "investigation_tickets", engine, schema="core", if_exists="append", index=False, chunksize=2000
    )
    print(f"Wrote {len(insert_df):,} investigation tickets to core.investigation_tickets")


if __name__ == "__main__":
    tickets = build_tickets()
    print(f"Built {len(tickets):,} tickets from High/Critical Ensemble flags "
          f"across {tickets['seller_id'].nunique() if not tickets.empty else 0} sellers")
    if not tickets.empty:
        print(tickets["severity"].value_counts())
        print(tickets["anomaly_type"].value_counts())
    write_tickets(tickets)
