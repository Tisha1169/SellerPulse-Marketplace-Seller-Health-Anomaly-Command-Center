"""
SLA tracking: marks tickets breached when the current time (or, for historical
simulated tickets, "now" = the dataset's simulation end date) has passed
sla_deadline while the ticket is still open (not Resolved/False_Positive).

Run this after any status update — it's cheap (single UPDATE) and keeps
is_sla_breached authoritative rather than computed ad hoc in the dashboard.
"""
import pandas as pd

from anomaly_engine.db import get_engine
from data_generator import config as cfg


def update_sla_breaches(as_of: pd.Timestamp = None):
    """
    Two cases count as breached: (1) a still-open ticket whose deadline has
    already passed as of `as_of`, and (2) a CLOSED ticket that was resolved
    after its own deadline — a late resolution is still a breach even though
    the ticket is no longer open; only checking open tickets would silently
    erase historical SLA misses the moment a case closes.
    """
    as_of = as_of or pd.Timestamp(cfg.SIMULATION_END_DATE)
    engine = get_engine()
    with engine.begin() as conn:
        result = conn.exec_driver_sql(
            """
            UPDATE core.investigation_tickets
            SET is_sla_breached = TRUE, updated_at = now()
            WHERE is_sla_breached = FALSE
              AND (
                    (status NOT IN ('Resolved', 'False_Positive', 'Escalated') AND sla_deadline < %(as_of)s)
                 OR (status IN ('Resolved', 'False_Positive', 'Escalated') AND resolved_at IS NOT NULL AND resolved_at > sla_deadline)
                 OR (status = 'Escalated' AND sla_deadline < %(as_of)s)
              )
            """,
            {"as_of": as_of},
        )
        breached = result.rowcount
    print(f"Marked {breached} tickets as SLA-breached as of {as_of.date()}")
    return breached


def sla_summary() -> pd.DataFrame:
    engine = get_engine()
    return pd.read_sql(
        """
        SELECT status,
               count(*) AS n_tickets,
               sum(CASE WHEN is_sla_breached THEN 1 ELSE 0 END) AS n_breached,
               round(100.0 * sum(CASE WHEN is_sla_breached THEN 1 ELSE 0 END) / count(*), 1) AS pct_breached
        FROM core.investigation_tickets
        GROUP BY status
        ORDER BY n_tickets DESC
        """,
        engine,
    )


if __name__ == "__main__":
    update_sla_breaches()
    print(sla_summary().to_string(index=False))
