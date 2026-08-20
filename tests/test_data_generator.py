"""
Tests for the synthetic data generator's distributional properties and internal
consistency — these catch the kind of bug that silently produces "realistic-
looking but wrong" data (e.g. a seller with zero products, an anomaly episode
that falls outside the order-generation window).
"""
import pandas as pd
import pytest

from data_generator import config as cfg
from data_generator.generate_sellers import generate_sellers
from data_generator.generate_products import generate_products
from data_generator.inject_anomalies import inject_anomalies


@pytest.fixture(scope="module")
def sellers_df():
    return generate_sellers(n_sellers=300)


class TestSellerGeneration:
    def test_segment_distribution_roughly_matches_config(self, sellers_df):
        observed = sellers_df["seller_segment"].value_counts(normalize=True)
        for segment, expected_weight in cfg.SELLER_SEGMENT_WEIGHTS.items():
            assert abs(observed.get(segment, 0) - expected_weight) < 0.08

    def test_no_duplicate_seller_ids(self, sellers_df):
        assert sellers_df["seller_id"].is_unique

    def test_tenure_cohort_consistent_with_signup_date(self, sellers_df):
        tenure_days = (pd.Timestamp(cfg.SIMULATION_END_DATE) - pd.to_datetime(sellers_df["signup_date"])).dt.days
        for cohort, (lo, hi) in cfg.TENURE_COHORT_DAYS_RANGE.items():
            mask = sellers_df["tenure_cohort"] == cohort
            assert (tenure_days[mask] >= lo - 1).all() and (tenure_days[mask] <= hi + 1).all()


class TestProductGeneration:
    def test_every_seller_has_at_least_one_product(self, sellers_df):
        products = generate_products(sellers_df, n_products=1000)
        sellers_with_products = set(products["seller_id"].unique())
        assert sellers_with_products == set(sellers_df["seller_id"].unique())

    def test_product_price_within_configured_tier_range(self, sellers_df):
        products = generate_products(sellers_df, n_products=1000)
        for tier, (lo, hi) in cfg.PRICE_TIER_RANGE.items():
            sub = products[products["price_tier"] == tier]
            assert (sub["list_price"] >= lo).all() and (sub["list_price"] <= hi).all()


class TestAnomalyInjection:
    def test_injected_sellers_are_a_subset_of_real_sellers(self, sellers_df):
        ground_truth = inject_anomalies(sellers_df)
        assert set(ground_truth["seller_id"]).issubset(set(sellers_df["seller_id"]))

    def test_episode_dates_within_order_generation_window(self, sellers_df):
        ground_truth = inject_anomalies(sellers_df)
        window_start = pd.Timestamp(cfg.SIMULATION_END_DATE) - pd.Timedelta(days=cfg.N_DAYS)
        window_end = pd.Timestamp(cfg.SIMULATION_END_DATE)
        assert (pd.to_datetime(ground_truth["start_date"]) >= window_start).all()
        assert (pd.to_datetime(ground_truth["end_date"]) <= window_end).all()

    def test_no_seller_gets_two_episodes(self, sellers_df):
        ground_truth = inject_anomalies(sellers_df)
        assert ground_truth["seller_id"].is_unique

    def test_episode_end_after_start(self, sellers_df):
        ground_truth = inject_anomalies(sellers_df)
        assert (pd.to_datetime(ground_truth["end_date"]) > pd.to_datetime(ground_truth["start_date"])).all()
