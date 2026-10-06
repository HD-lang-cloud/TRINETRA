"""
TRINETRA — Working Capital Optimization & Rebalancing Engine Tests (Phase 9, Spec §31, §32, §33)
Verifies Working Capital Pareto/Lorenz distributions, turnover ratios (ITR/DSI),
multi-echelon buffer rebalancing, dead stock reclamation playbooks, and holding cost sensitivity.
"""

import os
import sys
import pytest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
for p in [str(BASE_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app import create_app
from init_db import initialize_database
from utils.data_seeder import seed_demo_dataset
from services.capital_optimizer_service import CapitalOptimizerService


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    """Creates a temporary isolated SQLite database file and seeds it with demo data."""
    temp_dir = tmp_path_factory.mktemp("trinetra_capital")
    db_file = str(temp_dir / "test_capital_trinetra.db")
    initialize_database(db_file)
    seed_demo_dataset(db_path=db_file, seed=42)
    return db_file


@pytest.fixture
def client(test_db_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", test_db_path)
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    app_instance = create_app("testing")
    app_instance.config["DATABASE_PATH"] = test_db_path
    return app_instance.test_client()


def test_pareto_distribution_and_turnover_velocity(test_db_path):
    """Verifies Working Capital Pareto distribution, ITR turnover, DSI, and Gini coefficient (Spec §31)."""
    service = CapitalOptimizerService(db_path=test_db_path)
    analytics = service.get_pareto_and_velocity_analytics()

    summary = analytics["summary"]
    pareto_curve = analytics["pareto_curve"]
    sku_analytics = analytics["sku_analytics"]
    quadrants = analytics["quadrants"]

    # 1. Summary validation
    assert summary["total_working_capital_inr"] > 0
    assert summary["total_annual_cogs_inr"] > 0
    assert summary["portfolio_itr"] > 0
    assert summary["portfolio_dsi_days"] > 0
    assert 0.0 <= summary["capital_gini_coefficient"] <= 1.0

    # 2. Pareto ABC classification validation
    assert len(pareto_curve) >= 7
    abc_classes = {p["abc_class"] for p in pareto_curve}
    assert "A" in abc_classes
    assert "C" in abc_classes

    # Pareto curve must be monotonic non-decreasing in cumulative COGS
    for i in range(len(pareto_curve) - 1):
        assert pareto_curve[i]["cumulative_cogs_pct"] <= pareto_curve[i + 1]["cumulative_cogs_pct"]

    # 3. Capital Productivity Quadrants
    quadrant_keys = set(quadrants.keys())
    assert "CAPITAL_TRAP" in quadrant_keys or "HIGH_VELOCITY_STAR" in quadrant_keys
    # SKU-FAST-01 should have high turnover velocity
    fast_sku = next((s for s in sku_analytics if "SKU-FAST-01" in s["sku"]), None)
    assert fast_sku is not None
    assert fast_sku["itr"] > 2.0


def test_multi_echelon_buffer_rebalancing(test_db_path):
    """Verifies multi-echelon inventory buffer reallocation and capital release/injection (Spec §32)."""
    service = CapitalOptimizerService(db_path=test_db_path)
    result = service.rebalance_portfolio_buffers(budget_ceiling_inr=50000.0, service_level=0.95)

    summary = result["summary"]
    releases = result["capital_releases"]
    injections = result["capital_injections"]

    assert summary["target_service_level_pct"] == 95.0
    assert summary["total_capital_released_inr"] > 0
    assert summary["total_capital_injected_inr"] > 0
    assert "net_capital_delta_inr" in summary

    # Releases should identify overstocked inventory
    assert len(releases) >= 1
    for r in releases:
        assert r["excess_units"] > 0
        assert r["capital_released_inr"] > 0
        assert "FREEZE" in r["action"]

    # Injections should identify stockout-prone SKUs
    assert len(injections) >= 1
    for inj in injections:
        assert inj["deficit_units"] > 0
        assert inj["capital_required_inr"] > 0
        assert "EXPEDITE" in inj["action"]


def test_dead_stock_reclamation_playbook(test_db_path):
    """Verifies structured dead stock liquidation playbook across 4 reclamation strategies (Spec §33)."""
    service = CapitalOptimizerService(db_path=test_db_path)
    playbook = service.get_dead_stock_reclamation_playbook(holding_cost_rate=0.20)

    summary = playbook["summary"]
    dead_skus = playbook["dead_skus"]

    assert summary["dead_stock_skus_count"] >= 1
    assert summary["total_stagnant_capital_inr"] > 0
    assert summary["total_holding_cost_avoided_inr"] > 0
    assert summary["total_projected_recoverable_capital_inr"] > 0

    # Verify SKU-DEAD-04 is evaluated
    dead_item = next((d for d in dead_skus if "SKU-DEAD-04" in d["sku"]), None)
    assert dead_item is not None
    assert dead_item["tied_up_capital_inr"] > 0
    assert dead_item["annual_holding_cost_inr"] > 0

    # Verify 4 reclamation strategies
    strategies = {s["strategy"] for s in dead_item["strategies"]}
    assert "DISCOUNT_MARKDOWN" in strategies
    assert "SUPPLIER_BUYBACK" in strategies
    assert "COMPLEMENTARY_BUNDLE" in strategies
    assert "SALVAGE_SCRAP" in strategies


def test_holding_cost_sensitivity_analysis(test_db_path):
    """Verifies financial sensitivity curve calculation across varying holding cost rates."""
    service = CapitalOptimizerService(db_path=test_db_path)
    sensitivity = service.evaluate_holding_cost_sensitivity(rates=[0.15, 0.20, 0.25, 0.30])

    curve = sensitivity["sensitivity_curve"]
    assert len(curve) == 4

    # Holding cost must increase monotonically with rate
    assert curve[0]["total_annual_holding_cost_inr"] < curve[1]["total_annual_holding_cost_inr"]
    assert curve[1]["total_annual_holding_cost_inr"] < curve[2]["total_annual_holding_cost_inr"]
    assert curve[2]["total_annual_holding_cost_inr"] < curve[3]["total_annual_holding_cost_inr"]

    # Verify monthly cash drag is annual / 12
    for pt in curve:
        expected_monthly = round(pt["total_annual_holding_cost_inr"] / 12.0, 2)
        assert abs(pt["monthly_cash_drag_inr"] - expected_monthly) <= 0.05


def test_capital_rest_api_endpoints(client, test_db_path):
    """Verifies all REST API routes for capital overview, analytics, rebalancing, and dead stock."""
    # 1. GET /api/capital (Backwards-compatible overview)
    res1 = client.get("/api/capital")
    assert res1.status_code == 200
    data1 = res1.get_json()["data"]
    assert "capital" in data1
    assert "resilience" in data1

    # 2. GET /api/capital/analytics
    res2 = client.get("/api/capital/analytics")
    assert res2.status_code == 200
    data2 = res2.get_json()["data"]
    assert "summary" in data2
    assert "pareto_curve" in data2
    assert "sku_analytics" in data2

    # 3. POST /api/capital/rebalance
    res3 = client.post("/api/capital/rebalance", json={"budget_ceiling_inr": 25000, "service_level": 0.95})
    assert res3.status_code == 200
    data3 = res3.get_json()["data"]
    assert "summary" in data3
    assert "capital_releases" in data3
    assert "capital_injections" in data3

    # 4. GET /api/capital/dead-stock-reclamation
    res4 = client.get("/api/capital/dead-stock-reclamation?holding_cost_rate=0.25")
    assert res4.status_code == 200
    data4 = res4.get_json()["data"]
    assert "summary" in data4
    assert "dead_skus" in data4

    # 5. POST /api/capital/sensitivity
    res5 = client.post("/api/capital/sensitivity", json={"rates": [0.15, 0.25]})
    assert res5.status_code == 200
    data5 = res5.get_json()["data"]
    assert len(data5["sensitivity_curve"]) == 2
