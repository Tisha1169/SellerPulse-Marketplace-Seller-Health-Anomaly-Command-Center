"""
Unit tests for the anomaly engine's pure-logic pieces — no database required.
These exercise the functions that decide what gets promoted to an Ensemble flag,
since that logic is the crux of the precision/recall trade-off documented in
docs/evaluation_report.md and should not silently regress.
"""
import pandas as pd
import pytest

from anomaly_engine.ensemble import build_ensemble, MIN_METHOD_VOTES, MULTI_METRIC_DISTINCT_TYPE_THRESHOLD
from anomaly_engine.metric_config import severity_from_score, METRIC_ANOMALY_MAP


def _flag_row(seller_id, flag_date, anomaly_type, method, score=3.0):
    return {
        "seller_id": seller_id, "flag_date": flag_date, "anomaly_type": anomaly_type,
        "affected_metric": "defect_rate", "baseline_value": 0.01, "observed_value": 0.05,
        "deviation_abs": 0.04, "deviation_pct": 400.0, "method": method,
        "anomaly_score": score, "severity": severity_from_score(score),
        "reason_code": "test", "explanation": "test flag",
    }


class TestSeverityBands:
    def test_low_score_is_low_severity(self):
        assert severity_from_score(0.5) == "Low"

    def test_high_score_is_critical(self):
        assert severity_from_score(10.0) == "Critical"

    def test_boundary_is_inclusive(self):
        assert severity_from_score(6.0) == "Critical"
        assert severity_from_score(5.999) == "High"

    def test_every_metric_maps_to_a_known_severity_capable_type(self):
        for metric, (anomaly_type, direction) in METRIC_ANOMALY_MAP.items():
            assert anomaly_type
            assert direction in {"up", "down", "both"}


class TestEnsembleVoting:
    def test_single_method_never_promotes(self):
        """A lone method firing should not become an Ensemble flag — the whole
        point of the ensemble is requiring independent agreement."""
        flags = pd.DataFrame([_flag_row(1, pd.Timestamp("2026-01-01"), "Defect_Rate_Rise", "ZScore")])
        ensemble = build_ensemble(flags)
        assert ensemble.empty

    def test_two_methods_same_day_promotes_with_persistence(self):
        """Two methods agreeing on day 1 AND a nearby day (persistence) should promote."""
        flags = pd.DataFrame([
            _flag_row(1, pd.Timestamp("2026-01-01"), "Defect_Rate_Rise", "ZScore"),
            _flag_row(1, pd.Timestamp("2026-01-01"), "Defect_Rate_Rise", "IQR"),
            _flag_row(1, pd.Timestamp("2026-01-02"), "Defect_Rate_Rise", "ZScore"),
        ])
        ensemble = build_ensemble(flags)
        assert len(ensemble) == 1
        assert ensemble.iloc[0]["anomaly_type"] == "Defect_Rate_Rise"

    def test_two_methods_without_persistence_does_not_promote(self):
        """Two methods agree on a single isolated day with no nearby corroboration
        — this is exactly the chance-noise case the persistence filter targets."""
        flags = pd.DataFrame([
            _flag_row(1, pd.Timestamp("2026-01-01"), "Defect_Rate_Rise", "ZScore"),
            _flag_row(1, pd.Timestamp("2026-01-01"), "Defect_Rate_Rise", "IQR"),
        ])
        ensemble = build_ensemble(flags)
        assert ensemble.empty

    def test_three_distinct_types_relabels_multi_metric(self):
        seller, d = 1, pd.Timestamp("2026-01-01")
        d2 = pd.Timestamp("2026-01-02")
        flags = pd.DataFrame([
            _flag_row(seller, d, "Defect_Rate_Rise", "ZScore"),
            _flag_row(seller, d, "Defect_Rate_Rise", "IQR"),
            _flag_row(seller, d, "Return_Rate_Spike", "ZScore"),
            _flag_row(seller, d, "Return_Rate_Spike", "CUSUM"),
            _flag_row(seller, d, "Late_Shipment_Spike", "ZScore"),
            _flag_row(seller, d, "Late_Shipment_Spike", "IQR"),
            # persistence corroboration on a nearby day
            _flag_row(seller, d2, "Defect_Rate_Rise", "ZScore"),
            _flag_row(seller, d2, "Defect_Rate_Rise", "IQR"),
        ])
        ensemble = build_ensemble(flags)
        # the 3-distinct-type day relabels to Multi_Metric_Deterioration; the
        # persistence-corroboration day (d2) only has 1 distinct type on its own
        # and correctly stays labeled by its actual metric, not relabeled.
        day1_row = ensemble[ensemble["flag_date"] == d]
        assert (day1_row["anomaly_type"] == "Multi_Metric_Deterioration").all()
        assert len(day1_row) == 1

    def test_different_sellers_are_independent(self):
        flags = pd.DataFrame([
            _flag_row(1, pd.Timestamp("2026-01-01"), "Defect_Rate_Rise", "ZScore"),
            _flag_row(2, pd.Timestamp("2026-01-01"), "Defect_Rate_Rise", "IQR"),
        ])
        ensemble = build_ensemble(flags)
        assert ensemble.empty  # each seller only has 1 method voting for it
