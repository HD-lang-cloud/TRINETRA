import os
import sys
import pytest
import numpy as np
import pandas as pd
from pathlib import Path

# Add backend directory to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
for p in [str(BASE_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app import create_app
from init_db import initialize_database
from utils.data_seeder import seed_demo_dataset
from ml.preprocessing import prepare_time_series, engineer_features, temporal_train_test_split
from ml.models.baselines import NaiveBaseline, SeasonalNaiveBaseline, MovingAverageBaseline, HoltExponentialSmoothing
from ml.models.ml_regressor import MLForecaster
from ml.models.deep_learning import SequenceRecurrentForecaster
from ml.benchmarking import ForecastingBenchmark
from ml.service import ForecastingService
from repositories.product_repository import ProductRepository


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    """Creates a temporary isolated SQLite database file and seeds it with demo data."""
    temp_dir = tmp_path_factory.mktemp("trinetra_fc")
    db_file = str(temp_dir / "test_forecast_trinetra.db")
    initialize_database(db_file)
    seed_demo_dataset(db_path=db_file, seed=42)
    return db_file


@pytest.fixture
def app(test_db_path, monkeypatch):
    """Creates a test Flask application configured to use the seeded test database."""
    monkeypatch.setenv("DATABASE_PATH", test_db_path)
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    app_instance = create_app("testing")
    app_instance.config["DATABASE_PATH"] = test_db_path
    return app_instance


@pytest.fixture
def client(app):
    return app.test_client()


def test_temporal_train_test_split_no_leakage():
    """Verifies sequential splitting without future lookahead or data shuffling (Spec §56)."""
    dates = pd.date_range("2026-01-01", periods=60, freq="D")
    df = pd.DataFrame({"date": dates, "quantity": np.arange(60, dtype=float)})

    train_df, test_df = temporal_train_test_split(df, test_horizon=14)

    assert len(train_df) == 46
    assert len(test_df) == 14
    # Max date in train must be strictly before min date in test
    assert train_df["date"].max() < test_df["date"].min()
    assert test_df["date"].min() == train_df["date"].max() + pd.Timedelta(days=1)


def test_baseline_forecasting_models():
    """Tests all baseline candidate benchmarks (Naive, Seasonal Naive, Moving Average, Holt)."""
    series = np.array([10.0, 12.0, 14.0, 11.0, 13.0, 15.0, 16.0, 12.0, 14.0, 16.0])

    # 1. Naive
    naive = NaiveBaseline().fit(series)
    p_naive = naive.predict(horizon=5)
    assert len(p_naive) == 5
    assert np.all(p_naive == 16.0)

    # 2. Moving Average (3d)
    ma = MovingAverageBaseline(window=3).fit(series)
    p_ma = ma.predict(horizon=5)
    assert np.all(np.isclose(p_ma, 14.0))

    # 3. Holt Exponential Smoothing
    holt = HoltExponentialSmoothing().fit(series)
    p_holt = holt.predict(horizon=5)
    assert len(p_holt) == 5
    assert np.all(p_holt >= 0.0)


def test_ml_gradient_boosting_forecaster():
    """Tests tree-based machine learning with multi-step recursive forecasting."""
    dates = pd.date_range("2026-01-01", periods=40, freq="D")
    # Linear trend + weekly noise
    quantities = [float(10 + i * 0.5 + (i % 7)) for i in range(40)]
    df = pd.DataFrame({"date": dates, "quantity": quantities})

    ml_model = MLForecaster(model_type="gradient_boosting")
    ml_model.fit(df)
    assert ml_model.is_fitted is True

    preds = ml_model.predict(horizon=7)
    assert len(preds) == 7
    assert np.all(preds > 0.0)


def test_sequence_recurrent_deep_learning_gru():
    """Tests Gated Recurrent Unit neural network training and forward inference (Spec §57)."""
    # 60 days of sinusoidal demand
    x = np.linspace(0, 4 * np.pi, 60)
    series = 15.0 + 8.0 * np.sin(x)

    gru = SequenceRecurrentForecaster(seq_len=14, hidden_dim=16, epochs=25)
    gru.fit(series)
    assert gru.is_fitted is True

    preds = gru.predict(horizon=14)
    assert len(preds) == 14
    assert np.all(preds >= 0.0)


def test_data_sufficiency_gatekeeper(test_db_path):
    """
    Spec §15: Never generate a fake high-confidence deep-learning prediction from sparse data.
    Verifies that SKU-NEW-07 (only 5 observations) suppresses deep learning and falls back.
    """
    repo = ProductRepository(db_path=test_db_path)
    sparse_prod = repo.find_by_sku("SKU-NEW-07")

    fc_service = ForecastingService(db_path=test_db_path)
    output = fc_service.generate_and_save_forecast(sparse_prod["id"], horizon=14)

    suff = output["data_sufficiency"]
    assert suff["status"] == "INSUFFICIENT_SPARSE_DATA"
    assert suff["deep_learning_eligible"] is False
    assert suff["observations"] < 14
    # Champion must be a fallback baseline
    assert "Moving Average" in output["champion_model"]


def test_full_benchmark_and_champion_selection(test_db_path):
    """Verifies end-to-end multi-model benchmarking on full 90-day SKU (SKU-FAST-01)."""
    repo = ProductRepository(db_path=test_db_path)
    fast_prod = repo.find_by_sku("SKU-FAST-01")

    fc_service = ForecastingService(db_path=test_db_path)
    output = fc_service.generate_and_save_forecast(fast_prod["id"], horizon=14)

    assert output["data_sufficiency"]["status"] == "SUFFICIENT_DATA"
    assert len(output["benchmark_results"]) >= 4

    # Verify at least one champion was selected
    selected_champions = [b for b in output["benchmark_results"] if b.get("selected")]
    assert len(selected_champions) == 1
    champ = selected_champions[0]
    assert champ["mae"] < 25.0

    # Verify 14-day predictions with 80% and 95% confidence intervals
    preds = output["predictions"]
    assert len(preds) == 14
    for p in preds:
        assert p["predicted_demand"] >= 0.0
        assert p["interval_80"]["lower"] <= p["predicted_demand"] <= p["interval_80"]["upper"]
        assert p["interval_95"]["lower"] <= p["interval_80"]["lower"]
        assert p["interval_95"]["upper"] >= p["interval_80"]["upper"]


def test_forecasting_api_endpoints(client, test_db_path):
    """Verifies REST endpoints for forecasts, on-demand training, and Model Health."""
    repo = ProductRepository(db_path=test_db_path)
    fast_prod = repo.find_by_sku("SKU-FAST-01")

    # 1. GET forecast
    res1 = client.get(f"/api/forecasts/{fast_prod['id']}?horizon=14")
    assert res1.status_code == 200
    json1 = res1.get_json()["data"]
    assert json1["sku"] == "SKU-FAST-01"
    assert len(json1["predictions"]) == 14

    # 2. POST retrain
    res2 = client.post(f"/api/forecasts/{fast_prod['id']}/train?horizon=7")
    assert res2.status_code == 200
    json2 = res2.get_json()["data"]
    assert len(json2["predictions"]) == 7

    # 3. GET Model Health
    res3 = client.get("/api/forecasts/models/health")
    assert res3.status_code == 200
    json3 = res3.get_json()["data"]
    assert json3["status"] == "HEALTHY"
    assert "active_champions" in json3
