import os
import sys
import pytest
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
from services.dna_service import InventoryDNAService
from services.risk_service import RiskScoringEngine
from services.anomaly_service import AnomalyDetectionEngine
from services.capital_service import CapitalIntelligenceService
from repositories.product_repository import ProductRepository


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    """Creates a temporary isolated SQLite database file and seeds it with demo data."""
    temp_dir = tmp_path_factory.mktemp("trinetra_intel")
    db_file = str(temp_dir / "test_intel_trinetra.db")
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


def test_data_seeder_personas(test_db_path):
    """Verifies that seed_demo_dataset creates the 7 distinct product personas correctly."""
    repo = ProductRepository(db_path=test_db_path)
    all_prods = repo.find_all()
    skus = {p["sku"] for p in all_prods}

    required_archetypes = {
        "SKU-FAST-01", "SKU-SPIKE-02", "SKU-SPOF-03",
        "SKU-DEAD-04", "SKU-CAP-05", "SKU-SEAS-06", "SKU-NEW-07"
    }
    assert required_archetypes.issubset(skus), f"Missing archetypes: {required_archetypes - skus}"


def test_inventory_dna_behavioral_classifications(test_db_path):
    """Verifies that Inventory DNA accurately identifies Fast Movers, Dead Stock, and Sparse Data."""
    repo = ProductRepository(db_path=test_db_path)
    dna_service = InventoryDNAService(db_path=test_db_path)

    # 1. Fast Mover Test
    fast_prod = repo.find_by_sku("SKU-FAST-01")
    fast_dna = dna_service.calculate_dna(fast_prod["id"])
    fast_tags = [c["tag"] for c in fast_dna["classifications"]]
    assert "FAST MOVER" in fast_tags
    assert fast_dna["metrics"]["demand_velocity_daily"] >= 10.0

    # 2. Dead Stock Test
    dead_prod = repo.find_by_sku("SKU-DEAD-04")
    dead_dna = dna_service.calculate_dna(dead_prod["id"])
    dead_tags = [c["tag"] for c in dead_dna["classifications"]]
    assert "DEAD STOCK" in dead_tags

    # 3. Sparse Data Test (Data sufficiency gate)
    sparse_prod = repo.find_by_sku("SKU-NEW-07")
    sparse_dna = dna_service.calculate_dna(sparse_prod["id"])
    sparse_tags = [c["tag"] for c in sparse_dna["classifications"]]
    assert "SPARSE DATA" in sparse_tags
    assert sparse_dna["metrics"]["data_confidence_pct"] < 25.0


def test_risk_scoring_dimensions_and_evidence(test_db_path):
    """Verifies that 8-dimensional risk scoring produces bounded scores and clear evidence."""
    repo = ProductRepository(db_path=test_db_path)
    risk_engine = RiskScoringEngine(db_path=test_db_path)

    spike_prod = repo.find_by_sku("SKU-SPIKE-02")
    risk_profile = risk_engine.evaluate_product_risk(spike_prod["id"])

    # Stockout risk should be elevated due to demand surge
    dims = risk_profile["dimensions"]
    assert dims["stockout_risk_pct"] >= 70.0
    assert 0.0 <= dims["stockout_risk_pct"] <= 100.0
    assert 0.0 <= dims["overstock_risk_pct"] <= 100.0
    assert 0.0 <= dims["supplier_risk_pct"] <= 100.0
    assert 0.0 <= dims["lead_time_risk_pct"] <= 100.0

    # Evidence must contain explanations for dimensions
    evidence = risk_profile["evidence"]
    assert "reason" in evidence["stockout"]
    assert len(evidence["stockout"]["reason"]) > 10


def test_anomaly_detection_engine(test_db_path):
    """Verifies that statistical anomaly detection flags the recent demand surge in SKU-SPIKE-02."""
    repo = ProductRepository(db_path=test_db_path)
    anomaly_engine = AnomalyDetectionEngine(db_path=test_db_path)

    spike_prod = repo.find_by_sku("SKU-SPIKE-02")
    anomalies = anomaly_engine.scan_product_anomalies(spike_prod["id"])

    # Demand spike story should trigger Z-score or IQR outlier
    types = [a["anomaly_type"] for a in anomalies]
    assert any("DEMAND" in t for t in types)
    assert any(a["severity"] in ("HIGH", "CRITICAL") for a in anomalies)


def test_capital_intelligence_and_resilience_score(test_db_path):
    """Verifies working capital calculation and TRINETRA Resilience Index."""
    capital_service = CapitalIntelligenceService(db_path=test_db_path)

    capital = capital_service.get_capital_breakdown()
    assert capital["total_working_capital_inr"] > 0.0
    assert capital["dead_capital_inr"] > 0.0  # From SKU-DEAD-04
    assert 0.0 <= capital["capital_concentration_top3_pct"] <= 100.0

    resilience = capital_service.calculate_resilience_index()
    score = resilience["resilience_score"]
    assert 0.0 <= score <= 100.0
    assert resilience["rating"] in ("RESILIENT", "MODERATE", "VULNERABLE", "CRITICAL RISK")
    assert "formula" in resilience


def test_intelligence_api_endpoints(client):
    """Verifies REST endpoints for risks, DNA, capital, and anomalies."""
    # 1. Risks endpoint
    risks_res = client.get("/api/risks")
    assert risks_res.status_code == 200
    assert risks_res.get_json()["data"]["count"] >= 7

    # 2. Capital endpoint
    cap_res = client.get("/api/capital")
    assert cap_res.status_code == 200
    assert "capital" in cap_res.get_json()["data"]
    assert "resilience" in cap_res.get_json()["data"]

    # 3. Anomalies endpoint
    anom_res = client.get("/api/anomalies")
    assert anom_res.status_code == 200
    assert "anomalies" in anom_res.get_json()["data"]
