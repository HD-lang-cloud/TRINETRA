import time
import numpy as np
from ml.models.base_model import BaseForecaster


class NaiveBaseline(BaseForecaster):
    """
    Naive baseline benchmark (Spec §13).
    Projects the most recent observed demand forward across the entire horizon.
    """

    def __init__(self):
        super().__init__(name="Naive Baseline")
        self.last_value = 0.0

    def fit(self, train_data: np.ndarray, **kwargs) -> "NaiveBaseline":
        start = time.perf_counter()
        arr = np.asarray(train_data, dtype=float)
        self.last_value = float(arr[-1]) if len(arr) > 0 else 0.0
        self.is_fitted = True
        self.training_time_ms = round((time.perf_counter() - start) * 1000, 2)
        return self

    def predict(self, horizon: int) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted before predict()")
        return np.full(horizon, self.last_value, dtype=float)


class SeasonalNaiveBaseline(BaseForecaster):
    """
    Seasonal Naive benchmark using a 7-day weekly recurrence period.
    y_t = y_{t-7}
    """

    def __init__(self, season_length: int = 7):
        super().__init__(name=f"Seasonal Naive ({season_length}d)")
        self.season_length = season_length
        self.last_season = np.array([])

    def fit(self, train_data: np.ndarray, **kwargs) -> "SeasonalNaiveBaseline":
        start = time.perf_counter()
        arr = np.asarray(train_data, dtype=float)
        if len(arr) >= self.season_length:
            self.last_season = arr[-self.season_length:]
        elif len(arr) > 0:
            self.last_season = np.full(self.season_length, float(np.mean(arr)))
        else:
            self.last_season = np.zeros(self.season_length)

        self.is_fitted = True
        self.training_time_ms = round((time.perf_counter() - start) * 1000, 2)
        return self

    def predict(self, horizon: int) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted before predict()")
        # Tile the seasonal pattern to cover the horizon
        reps = int(np.ceil(horizon / self.season_length))
        tiled = np.tile(self.last_season, reps)
        return tiled[:horizon].astype(float)


class MovingAverageBaseline(BaseForecaster):
    """
    Moving Average benchmark using a sliding window (default 7 days).
    """

    def __init__(self, window: int = 7):
        super().__init__(name=f"Moving Average ({window}d)")
        self.window = window
        self.avg_value = 0.0

    def fit(self, train_data: np.ndarray, **kwargs) -> "MovingAverageBaseline":
        start = time.perf_counter()
        arr = np.asarray(train_data, dtype=float)
        if len(arr) >= self.window:
            self.avg_value = float(np.mean(arr[-self.window:]))
        elif len(arr) > 0:
            self.avg_value = float(np.mean(arr))
        else:
            self.avg_value = 0.0

        self.is_fitted = True
        self.training_time_ms = round((time.perf_counter() - start) * 1000, 2)
        return self

    def predict(self, horizon: int) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted before predict()")
        return np.full(horizon, self.avg_value, dtype=float)


class HoltExponentialSmoothing(BaseForecaster):
    """
    Holt's Linear Exponential Smoothing model (capturing level alpha and trend beta).
    """

    def __init__(self, alpha: float = 0.3, beta: float = 0.1):
        super().__init__(name="Holt Exponential Smoothing")
        self.alpha = alpha
        self.beta = beta
        self.level = 0.0
        self.trend = 0.0

    def fit(self, train_data: np.ndarray, **kwargs) -> "HoltExponentialSmoothing":
        start = time.perf_counter()
        arr = np.asarray(train_data, dtype=float)

        if len(arr) < 2:
            self.level = float(arr[-1]) if len(arr) > 0 else 0.0
            self.trend = 0.0
            self.is_fitted = True
            return self

        # Initialize level and trend
        level = arr[0]
        trend = arr[1] - arr[0]

        for t in range(1, len(arr)):
            val = arr[t]
            last_level = level
            level = self.alpha * val + (1 - self.alpha) * (level + trend)
            trend = self.beta * (level - last_level) + (1 - self.beta) * trend

        self.level = float(level)
        self.trend = float(trend)
        self.is_fitted = True
        self.training_time_ms = round((time.perf_counter() - start) * 1000, 2)
        return self

    def predict(self, horizon: int) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("Model must be fitted before predict()")
        preds = []
        for h in range(1, horizon + 1):
            pred = max(0.0, self.level + h * self.trend)
            preds.append(pred)
        return np.array(preds, dtype=float)
