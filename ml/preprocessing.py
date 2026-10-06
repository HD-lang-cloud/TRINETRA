import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple


def prepare_time_series(demand_records: List[Dict]) -> pd.DataFrame:
    """
    Validates, sorts, and cleans raw historical demand records into a continuous daily time series.
    Missing calendar dates are filled with 0.0 demand (no leakage, no negative values).
    """
    if not demand_records:
        return pd.DataFrame(columns=["date", "quantity"])

    df = pd.DataFrame(demand_records)
    df["date"] = pd.to_datetime(df["date"])
    df["quantity"] = df["quantity_demanded"].astype(float).clip(lower=0.0)
    df = df.sort_values("date").drop_duplicates(subset=["date"])

    # Reindex to continuous daily frequency to ensure no missing dates
    full_idx = pd.date_range(start=df["date"].min(), end=df["date"].max(), freq="D")
    df = df.set_index("date").reindex(full_idx, fill_value=0.0).reset_index()
    df.rename(columns={"index": "date"}, inplace=True)

    return df


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extracts time-series features without future data leakage (Spec §56):
    - Lagged demand: t-1, t-7, t-14
    - Rolling window statistics: 7-day mean, 14-day mean, 7-day standard deviation
    - Calendar features: day_of_week, is_weekend, day_of_month
    """
    df = df.copy()

    # Lags (strictly backward-looking)
    df["lag_1"] = df["quantity"].shift(1)
    df["lag_7"] = df["quantity"].shift(7)
    df["lag_14"] = df["quantity"].shift(14)

    # Rolling statistics shifted by 1 to prevent target leakage
    df["rolling_mean_7"] = df["quantity"].shift(1).rolling(window=7, min_periods=1).mean()
    df["rolling_mean_14"] = df["quantity"].shift(1).rolling(window=14, min_periods=1).mean()
    df["rolling_std_7"] = df["quantity"].shift(1).rolling(window=7, min_periods=1).std().fillna(0.0)

    # Calendar features
    df["day_of_week"] = df["date"].dt.dayofweek
    df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)
    df["day_of_month"] = df["date"].dt.day

    return df


def temporal_train_test_split(
    df: pd.DataFrame, test_horizon: int = 14
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Splits time series sequentially without shuffling to guarantee zero future data leakage.
    Last `test_horizon` days are reserved for holdout validation.
    """
    if len(df) <= test_horizon:
        # If insufficient points for full split, reserve last 20% for test
        split_idx = max(1, int(len(df) * 0.8))
        return df.iloc[:split_idx].copy(), df.iloc[split_idx:].copy()

    split_idx = len(df) - test_horizon
    train_df = df.iloc[:split_idx].copy()
    test_df = df.iloc[split_idx:].copy()
    return train_df, test_df
