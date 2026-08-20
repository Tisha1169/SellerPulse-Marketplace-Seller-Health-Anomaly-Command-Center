"""Unit tests for the scoring functions — pure pandas/numpy logic, no database."""
import pandas as pd

from scoring.health_score import _normalize_bad_is_high, _normalize_bad_is_low, _tier, WEIGHTS
from scoring.priority_score import _percentile_rank_0_100, WEIGHTS as PRIORITY_WEIGHTS


class TestHealthScoreNormalization:
    def test_zero_is_perfectly_healthy(self):
        series = pd.Series([0.0, 0.01, 0.02, 0.05, 0.10])
        result = _normalize_bad_is_high(series)
        assert result.iloc[0] == 100.0

    def test_ceiling_or_worse_is_zero(self):
        series = pd.Series([0.0] * 20 + [1.0])  # 1.0 is an extreme outlier -> near/at 95th pct ceiling
        result = _normalize_bad_is_high(series)
        assert result.iloc[-1] <= 5.0  # clipped near zero, not negative

    def test_output_always_in_bounds(self):
        series = pd.Series([0.0, 0.5, 1.0, 5.0, -1.0])  # includes a nonsensical negative
        result = _normalize_bad_is_high(series)
        assert (result >= 0).all() and (result <= 100).all()

    def test_rating_five_is_healthy_rating_one_is_unhealthy(self):
        series = pd.Series([5.0, 3.0, 1.0])
        result = _normalize_bad_is_low(series)
        assert result.iloc[0] > result.iloc[1] > result.iloc[2]
        assert result.iloc[0] == 100.0

    def test_weights_sum_to_one(self):
        assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

    def test_tier_bands_cover_full_range(self):
        assert _tier(100) == "Healthy"
        assert _tier(80) == "Healthy"
        assert _tier(79.9) == "Watch"
        assert _tier(0) == "Critical"


class TestPriorityScore:
    def test_weights_sum_to_one(self):
        assert abs(sum(PRIORITY_WEIGHTS.values()) - 1.0) < 1e-9

    def test_percentile_rank_is_monotonic(self):
        series = pd.Series([10, 50, 5, 100, 25])
        result = _percentile_rank_0_100(series)
        assert result[3] == 100.0  # the max value gets the top percentile
        assert result[2] == result.min()  # the min value gets the bottom percentile

    def test_percentile_rank_bounded_0_100(self):
        series = pd.Series(range(50))
        result = _percentile_rank_0_100(series)
        assert (result >= 0).all() and (result <= 100).all()
