"""
The daily orchestrator: generate/load -> validate -> transform metrics -> detect
anomalies -> score -> build investigation queue -> track SLA.

Run with: python -m pipeline.run_daily_pipeline
Add --skip-generate to reuse existing CSVs/DB data (e.g. when only re-running
detection after a threshold tweak) instead of regenerating synthetic data.

In production this would be an Airflow DAG with per-task retries, alerting on
DQ failure, and incremental (not full-truncate) loads. This is a linear Python
script with clear stage boundaries and logging instead — the right scope for a
single-node daily batch job, and the same stage structure maps directly onto DAG
tasks if this were ever migrated to Airflow (see docker/airflow/ note in
docs/architecture.md for why that wasn't done here).
"""
import argparse
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("sellerpulse.pipeline")


def _stage(name):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            log.info(f"START  {name}")
            t0 = time.time()
            try:
                result = fn(*args, **kwargs)
            except Exception:
                log.exception(f"FAILED {name}")
                raise
            log.info(f"DONE   {name} ({time.time() - t0:.1f}s)")
            return result
        return wrapper
    return decorator


@_stage("1/8 generate synthetic data")
def stage_generate():
    from data_generator.run_generator import main as generate_main
    generate_main()


@_stage("2/8 load into Postgres")
def stage_load():
    from database.seed_load import run_ddl, load_csvs
    from database.seed_load import create_engine, DB_URL
    engine = create_engine(DB_URL)
    run_ddl(engine)
    load_csvs(engine)


@_stage("3/8 data quality checks")
def stage_dq():
    from pipeline.data_quality_checks import main as dq_main
    report = dq_main()
    if (report["status"] == "FAIL").any():
        raise RuntimeError("Data quality checks failed — halting pipeline before analytics run on bad data.")


@_stage("4/8 transform daily metrics + baselines")
def stage_transform():
    import subprocess
    from anomaly_engine.db import get_engine
    engine = get_engine()
    for f in ["sql_analytics/seller_daily_metrics.sql", "sql_analytics/rolling_stats.sql", "sql_analytics/cohort_baselines.sql"]:
        log.info(f"  running {f}")
        with open(f) as fh, engine.begin() as conn:
            conn.exec_driver_sql(fh.read())


@_stage("5/8 anomaly detection + ensemble")
def stage_detect():
    from anomaly_engine.ensemble import collect_all_flags, build_ensemble, write_flags_to_db
    all_flags = collect_all_flags()
    ensemble = build_ensemble(all_flags)
    write_flags_to_db(all_flags, ensemble)
    log.info(f"  {len(all_flags):,} individual flags, {len(ensemble):,} ensemble flags")


@_stage("6/8 scoring (health + priority)")
def stage_score():
    from scoring.health_score import compute_health_scores, write_health_scores
    scores = compute_health_scores()
    write_health_scores(scores)


@_stage("7/8 investigation queue + SLA")
def stage_investigate():
    from investigation.queue_builder import build_tickets, write_tickets
    from investigation.simulate_investigation_actions import simulate, write_back
    from investigation.sla_engine import update_sla_breaches
    from anomaly_engine.db import get_engine
    import pandas as pd

    tickets = build_tickets()
    write_tickets(tickets)

    engine = get_engine()
    tickets_full = pd.read_sql(
        "SELECT t.*, f.anomaly_type FROM core.investigation_tickets t "
        "JOIN core.fact_anomaly_flags f ON f.flag_id = t.primary_flag_id",
        engine, parse_dates=["detected_date"],
    )
    if not tickets_full.empty:
        simulated = simulate(tickets_full)
        write_back(simulated)
    update_sla_breaches()


@_stage("8/8 evaluation report")
def stage_evaluate():
    from anomaly_engine.evaluate import main as evaluate_main
    evaluate_main()


def main():
    parser = argparse.ArgumentParser(description="SellerPulse daily pipeline")
    parser.add_argument("--skip-generate", action="store_true", help="Reuse existing data instead of regenerating")
    parser.add_argument("--skip-load", action="store_true", help="Reuse existing DB contents instead of reloading")
    args = parser.parse_args()

    t0 = time.time()
    log.info("=== SellerPulse daily pipeline starting ===")

    if not args.skip_generate:
        stage_generate()
    else:
        log.info("SKIP   1/8 generate synthetic data")

    if not args.skip_load:
        stage_load()
    else:
        log.info("SKIP   2/8 load into Postgres")

    stage_dq()
    stage_transform()
    stage_detect()
    stage_score()
    stage_investigate()
    stage_evaluate()

    log.info(f"=== Pipeline complete in {time.time() - t0:.1f}s ===")


if __name__ == "__main__":
    main()
