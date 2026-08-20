"""Generate dim_customer."""
import os

import numpy as np
import pandas as pd
from faker import Faker

from data_generator import config as cfg

fake = Faker()
Faker.seed(cfg.RANDOM_SEED + 2)
rng = np.random.default_rng(cfg.RANDOM_SEED + 2)


def _weighted_choice(weights_dict: dict, n: int) -> np.ndarray:
    keys = list(weights_dict.keys())
    probs = np.array(list(weights_dict.values()))
    probs = probs / probs.sum()
    return rng.choice(keys, size=n, p=probs)


def generate_customers(n_customers: int = cfg.N_CUSTOMERS) -> pd.DataFrame:
    customer_id = np.arange(1, n_customers + 1)
    country = _weighted_choice(cfg.COUNTRY_WEIGHTS, n_customers)
    region = [rng.choice(cfg.COUNTRIES_REGIONS[c]) for c in country]
    customer_segment = _weighted_choice(cfg.CUSTOMER_SEGMENT_WEIGHTS, n_customers)

    tenure_days = rng.integers(0, cfg.N_DAYS + 365, size=n_customers)
    signup_date = [cfg.SIMULATION_END_DATE - pd.Timedelta(days=int(d)) for d in tenure_days]

    df = pd.DataFrame(
        {
            "customer_id": customer_id,
            "signup_date": signup_date,
            "region": region,
            "customer_segment": customer_segment,
        }
    )
    return df


def generate_dim_date(n_days: int = cfg.N_DAYS + 365) -> pd.DataFrame:
    dates = pd.date_range(end=cfg.SIMULATION_END_DATE, periods=n_days, freq="D")
    us_holidays = {"01-01", "07-04", "11-28", "12-25", "12-31"}
    df = pd.DataFrame({"date_key": dates.date})
    df["day_of_week"] = dates.dayofweek
    df["day_name"] = dates.day_name()
    df["week_of_year"] = dates.isocalendar().week.to_numpy()
    df["month_num"] = dates.month
    df["month_name"] = dates.month_name()
    df["quarter"] = dates.quarter
    df["year"] = dates.year
    df["is_weekend"] = dates.dayofweek >= 5
    df["is_holiday"] = dates.strftime("%m-%d").isin(us_holidays)
    df["fiscal_period"] = "FY" + dates.year.astype(str) + "-Q" + dates.quarter.astype(str)
    return df


if __name__ == "__main__":
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)

    customers_df = generate_customers()
    customers_df.to_csv(os.path.join(cfg.OUTPUT_DIR, "dim_customer.csv"), index=False)
    print(f"Generated {len(customers_df)} customers -> {cfg.OUTPUT_DIR}/dim_customer.csv")

    date_df = generate_dim_date()
    date_df.to_csv(os.path.join(cfg.OUTPUT_DIR, "dim_date.csv"), index=False)
    print(f"Generated {len(date_df)} dates -> {cfg.OUTPUT_DIR}/dim_date.csv")
