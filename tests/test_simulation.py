import os
import sys
import pytest
from pathlib import Path

# Add backend and project root directory to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
for p in [str(BASE_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app import create_app
from init_db import initialize_database
from utils.data_seeder import seed_demo_dataset
from database import get_db_connection
from services.digital_twin import ShockConfig
from services.digital_twin.simulator import DigitalTwinEngine
from services.simulation_service import SimulationService


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    """Creates a temporary isolated SQLite database file and seeds it with demo data."""
    temp_dir = tmp_path_factory.mktemp("trinetra_sim")
    db_file = str(temp_dir / "test_sim_trinetra.db")
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


def test_in_memory_network_clone_no_mutation(test_db_path):
    """Verifies that Digital Twin decouples from database and never mutates production state (Spec §21)."""
    engine = DigitalTwinEngine(db_path=test_db_path)
    clone = engine.clone_network_state()

    assert "products" in clone
    assert "suppliers" in clone
    assert len(clone["products"]) >= 6

    # Mutate the clone in-memory
    first_sku = next(iter(clone["products"].keys()))
    clone["products"][first_sku]["quantity"] = 99999

    # Verify live SQLite database is completely untouched
    conn = get_db_connection(test_db_path)
    try:
        row = conn.execute("SELECT quantity FROM products WHERE sku = ?", (first_sku,)).fetchone()
        assert row["quantity"] != 99999
    finally:
        conn.close()


def test_baseline_simulation_run(test_db_path):
    """Verifies baseline discrete-event stepping produces steady-state operations."""
    engine = DigitalTwinEngine(db_path=test_db_path)
    net_state = engine.clone_network_state()

    horizon = 30
    states = engine.simulate_run(net_state, shock=None, horizon_days=horizon, seed=42)

    assert len(states) == horizon
    for s in states:
        assert s.day >= 1
        assert s.total_on_hand >= 0
        assert s.units_fulfilled >= 0
        assert s.units_demanded >= 0


def test_canonical_supplier_outage_shock(test_db_path):
    """Verifies supplier outage stress testing and resilience degradation (Spec §22)."""
    engine = DigitalTwinEngine(db_path=test_db_path)

    shock = ShockConfig(
        shock_type="SUPPLIER_OUTAGE",
        name="Test 30-Day Supplier Outage",
        description="Supplier shut down completely",
        target_supplier_id=5,
        start_day=5,
        duration_days=25
    )

    res = engine.run_stress_test(shock, horizon_days=40, seed=42)
    summary = res["impact_summary"]

    assert summary["projected_stockout_incidents"] >= 0
    assert summary["revenue_exposure_inr"] >= 0.0
    assert summary["resilience_score_delta"] <= 0.0
    assert len(res["trajectory"]) == 40
    assert len(res["mitigation_options"]) == 3


def test_canonical_demand_surge_shock(test_db_path):
    """Verifies viral demand surge shock multiplies demand and triggers stockouts (Spec §22)."""
    engine = DigitalTwinEngine(db_path=test_db_path)

    shock = ShockConfig(
        shock_type="DEMAND_SURGE",
        name="Sensor Demand Surge",
        description="3x demand spike on Sensors",
        target_category="Sensors",
        start_day=7,
        duration_days=15,
        magnitude=3.0
    )

    res = engine.run_stress_test(shock, horizon_days=30, seed=42)
    summary = res["impact_summary"]

    assert summary["service_level_drop_pct"] >= 0.0
    # Shocked service level must be lower than or equal to baseline
    assert summary["shocked_service_level_pct"] <= summary["baseline_service_level_pct"]


def test_correlated_cascading_failure(test_db_path):
    """Verifies compound shock (outage + demand surge) stress impact (Spec §22)."""
    engine = DigitalTwinEngine(db_path=test_db_path)

    shock = ShockConfig(
        shock_type="CORRELATED_FAILURE",
        name="Correlated Failure Test",
        description="Outage + surge compound shock",
        target_supplier_id=1,
        target_category="Semiconductors",
        start_day=5,
        duration_days=20,
        magnitude=2.5
    )

    res = engine.run_stress_test(shock, horizon_days=35, seed=42)
    assert len(res["critical_skus"]) >= 1


def test_actionable_mitigation_strategies(test_db_path):
    """Verifies trade-off calculations for mitigation options (Spec §23)."""
    sim_service = SimulationService(db_path=test_db_path)
    res = sim_service.run_stress_test({
        "shock_type": "SUPPLIER_OUTAGE",
        "name": "Mitigation Test Outage",
        "target_supplier_id": 2,
        "duration_days": 20
    })

    mitigations = res["mitigation_options"]
    assert len(mitigations) == 3

    # Ensure implementation cost and net savings are reported
    for m in mitigations:
        assert "strategy" in m
        assert "implementation_cost_inr" in m
        assert "risk_mitigation_pct" in m
        assert "recommendation" in m


def test_simulation_api_endpoints(client, test_db_path):
    """Verifies REST endpoints for presets, execution, and scenario detail."""
    # 1. GET Presets
    res1 = client.get("/api/simulation/presets")
    assert res1.status_code == 200
    presets = res1.get_json()["data"]["presets"]
    assert len(presets) == 5

    # 2. POST Run Simulation
    res2 = client.post("/api/simulation/run", json={
        "shock_type": "LEAD_TIME_INFLATION",
        "name": "Port Congestion Simulation",
        "magnitude": 14.0,
        "duration_days": 30
    })
    assert res2.status_code == 200
    sim_data = res2.get_json()["data"]
    assert "scenario_id" in sim_data
    assert "impact_summary" in sim_data
    scen_id = sim_data["scenario_id"]

    # 3. GET List Scenarios
    res3 = client.get("/api/simulation/scenarios")
    assert res3.status_code == 200
    assert res3.get_json()["data"]["count"] >= 1

    # 4. GET Scenario Detail
    res4 = client.get(f"/api/simulation/scenarios/{scen_id}")
    assert res4.status_code == 200
    detail = res4.get_json()["data"]
    assert detail["name"] == "Port Congestion Simulation"
    assert "mitigation_options" in detail["results"]
