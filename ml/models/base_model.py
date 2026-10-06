import numpy as np
from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseForecaster(ABC):
    """
    Abstract base class for all TRINETRA forecasting candidates (Spec §13, §14).
    Enforces unified interfaces for training, multi-step inference, and evaluation metrics.
    """

    def __init__(self, name: str):
        self.name = name
        self.is_fitted = False
        self.training_time_ms = 0.0

    @abstractmethod
    def fit(self, train_data: np.ndarray, **kwargs) -> "BaseForecaster":
        """Fits the model onto training series."""
        pass

    @abstractmethod
    def predict(self, horizon: int) -> np.ndarray:
        """Generates future point predictions for horizon steps."""
        pass

    @staticmethod
    def calculate_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
        """
        Calculates standard time-series validation metrics (Spec §14):
        - MAE: Mean Absolute Error
        - RMSE: Root Mean Squared Error
        - sMAPE: Symmetric Mean Absolute Percentage Error (%)
        - Bias: Mean Forecast Error (positive = over-forecasting, negative = under-forecasting)
        """
        y_t = np.asarray(y_true, dtype=float)
        y_p = np.asarray(y_pred, dtype=float).clip(min=0.0)

        if len(y_t) == 0:
            return {"mae": 0.0, "rmse": 0.0, "smape": 0.0, "bias": 0.0}

        errors = y_p - y_t
        abs_errors = np.abs(errors)

        mae = float(np.mean(abs_errors))
        rmse = float(np.sqrt(np.mean(errors ** 2)))

        # Symmetric MAPE: 100% * 2 * |y - y_hat| / (|y| + |y_hat|)
        denominator = (np.abs(y_t) + np.abs(y_p)) / 2.0
        # Avoid division by zero
        valid_idx = denominator > 1e-5
        if np.any(valid_idx):
            smape = float(np.mean(abs_errors[valid_idx] / denominator[valid_idx]) * 100.0)
        else:
            smape = 0.0

        bias = float(np.mean(errors))

        return {
            "mae": round(mae, 2),
            "rmse": round(rmse, 2),
            "smape": round(smape, 2),
            "bias": round(bias, 2)
        }
