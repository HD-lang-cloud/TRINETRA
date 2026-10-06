import time
import numpy as np
import pandas as pd
from typing import Optional
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from ml.models.base_model import BaseForecaster
from ml.preprocessing import engineer_features


class MLForecaster(BaseForecaster):
    """
    Supervised Machine Learning forecaster using Gradient Boosted / Random Forest decision trees (Spec §13).
    Extracts lag and calendar features and executes recursive multi-step forecasting across the prediction horizon.
    """

    def __init__(self, model_type: str = "gradient_boosting", n_estimators: int = 50, max_depth: int = 4):
        name = "Gradient Boosted Trees (ML)" if model_type == "gradient_boosting" else "Random Forest (ML)"
        super().__init__(name=name)
        self.model_type = model_type
        self.n_estimators = n_estimators
        self.max_depth = max_depth

        if model_type == "gradient_boosting":
            self.model = GradientBoostingRegressor(
                n_estimators=n_estimators, max_depth=max_depth, random_state=42
            )
        else:
            self.model = RandomForestRegressor(
                n_estimators=n_estimators, max_depth=max_depth, random_state=42
            )

        self.last_history_df: Optional[pd.DataFrame] = None
        self.feature_cols = [
            "lag_1", "lag_7", "lag_14", "rolling_mean_7",
            "rolling_mean_14", "rolling_std_7", "day_of_week", "is_weekend"
        ]

    def fit(self, train_df: pd.DataFrame, **kwargs) -> "MLForecaster":
        """
        Fits tree-based regressor on engineered lag/rolling features.
        Drops initial warm-up rows containing NaNs.
        """
        start = time.perf_counter()

        feat_df = engineer_features(train_df)
        clean_df = feat_df.dropna(subset=self.feature_cols)

        if len(clean_df) < 5:
            # Not enough data after lags to train trees
            self.is_fitted = False
            return self

        X = clean_df[self.feature_cols].values
        y = clean_df["quantity"].values

        self.model.fit(X, y)
        self.last_history_df = train_df.copy()
        self.is_fitted = True
        self.training_time_ms = round((time.perf_counter() - start) * 1000, 2)
        return self

    def predict(self, horizon: int) -> np.ndarray:
        """
        Recursive multi-step forecasting: iteratively appends predictions,
        re-engineers lag features, and steps forward sequentially.
        """
        if not self.is_fitted or self.last_history_df is None:
            raise RuntimeError("Model must be fitted before predict()")

        current_df = self.last_history_df.copy()
        predictions = []

        last_date = current_df["date"].max()

        for step in range(1, horizon + 1):
            next_date = last_date + pd.Timedelta(days=step)
            
            # Temporary row for next step
            temp_row = pd.DataFrame([{
                "date": next_date,
                "quantity": 0.0  # Placeholder to be filled
            }])
            extended_df = pd.concat([current_df, temp_row], ignore_index=True)
            feat_df = engineer_features(extended_df)

            # Extract features of the last row
            target_features = feat_df.iloc[-1:][self.feature_cols].fillna(0.0).values
            pred_val = float(self.model.predict(target_features)[0])
            pred_val = max(0.0, pred_val)

            predictions.append(pred_val)

            # Update placeholder in current_df with predicted value for next recursion
            temp_row["quantity"] = pred_val
            current_df = pd.concat([current_df, temp_row], ignore_index=True)

        return np.array(predictions, dtype=float)
