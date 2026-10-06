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
from repositories.product_repository import ProductRepository
from services.replenishment_service import ReplenishmentService


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    """Creates a temporary isolated SQLite database file and seeds it with demo data."""
    temp_dir = tmp_path_factory.mktemp("trinetra_replenish")
    db_file = str(temp_dir / "test_replenish_trinetra.db")
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


def test_rop_and_safety_stock_calculation(test_db_path):
    """Verifies stochastic ROP formula with lead-time demand and variance (Spec §17)."""
    repo = ProductRepository(db_path=test_db_path)
    fast_prod = repo.find_by_sku("SKU-FAST-01")

    service = ReplenishmentService(db_path=test_db_path)
    rop_95 = service.calculate_rop(fast_prod["id"], service_level=0.95)

    assert rop_95["sku"] == "SKU-FAST-01"
    assert rop_95["avg_daily_demand"] > 0
    assert rop_95["safety_stock"] > 0
    assert rop_95["reorder_point"] > rop_95["safety_stock"]
    assert rop_95["reorder_point"] >= rop_95["lead_time_demand"]

    # Higher service level (99%) must produce higher safety stock
    rop_99 = service.calculate_rop(fast_prod["id"], service_level=0.99)
    assert rop_99["safety_stock"] >= rop_95["safety_stock"]
    assert rop_99["reorder_point"] >= rop_95["reorder_point"]


def test_eoq_and_moq_constraint_optimization(test_db_path):
    """Verifies Economic Order Quantity calculation and supplier MOQ constraint (Spec §18)."""
    repo = ProductRepository(db_path=test_db_path)
    fast_prod = repo.find_by_sku("SKU-FAST-01")

    service = ReplenishmentService(db_path=test_db_path)
    eoq_data = service.calculate_eoq(fast_prod["id"], order_cost=500.0, holding_rate=0.20)

    assert eoq_data["sku"] == "SKU-FAST-01"
    assert eoq_data["theoretical_eoq"] > 0
    # Must respect MOQ constraint
    assert eoq_data["optimized_order_quantity"] >= eoq_data["moq"]
    assert eoq_data["total_annual_cost_inr"] > 0
    assert len(eoq_data["cost_curve"]) == 5


def test_replenishment_recommendation_generation(test_db_path):
    """Verifies catalog scan and urgency categorization (Spec §19)."""
    service = ReplenishmentService(db_path=test_db_path)
    recs = service.generate_recommendations(service_level=0.95)

    assert len(recs) > 0

    # Ensure critical items have proper evidence
    critical_recs = [r for r in recs if r["urgency"] == "CRITICAL"]
    assert len(critical_recs) >= 1

    crit = critical_recs[0]
    assert crit["recommended_quantity"] > 0
    assert crit["total_investment_inr"] > 0
    assert "evidence" in crit
    assert "rop" in crit["evidence"]
    assert "safety_stock" in crit["evidence"]


def test_multi_sku_purchase_order_consolidation(test_db_path):
    """Verifies grouping recommendations by supplier into consolidated POs (Spec §19, §20)."""
    service = ReplenishmentService(db_path=test_db_path)
    recs = service.generate_recommendations(service_level=0.95)
    rec_ids = [r["id"] for r in recs[:3] if "id" in r]

    pos = service.consolidate_purchase_orders(rec_ids, notes="Batch weekly order")
    assert len(pos) >= 1

    first_po = pos[0]
    assert first_po["po_number"].startswith("PO-")
    assert first_po["status"] == "DRAFT"
    assert first_po["total_amount"] > 0
    assert len(first_po["items"]) >= 1


def test_purchase_order_lifecycle_and_inbound_receipt(test_db_path):
    """
    Verifies PO status transitions (DRAFT -> APPROVED -> SENT -> RECEIVED).
    When marked RECEIVED, must book inbound PURCHASE movement and update product quantity (Spec §20, §35).
    """
    service = ReplenishmentService(db_path=test_db_path)
    repo = ProductRepository(db_path=test_db_path)
    crit_prod = repo.find_by_sku("SKU-SPIKE-02")
    initial_qty = crit_prod["quantity"]

    # Generate recommendation and PO for crit_prod
    recs = service.generate_recommendations()
    target_rec = next(r for r in recs if r["sku"] == "SKU-SPIKE-02")

    pos = service.consolidate_purchase_orders([target_rec["id"]])
    po_id = pos[0]["id"]
    ordered_qty = next(item["quantity"] for item in pos[0]["items"] if item["sku"] == "SKU-SPIKE-02")

    # Transition to APPROVED
    s1 = service.update_po_status(po_id, "APPROVED")
    assert s1["current_status"] == "APPROVED"

    # Transition to SENT
    s2 = service.update_po_status(po_id, "SENT")
    assert s2["current_status"] == "SENT"

    # Transition to RECEIVED (Books stock receipt!)
    s3 = service.update_po_status(po_id, "RECEIVED")
    assert s3["current_status"] == "RECEIVED"

    # Verify inventory was updated
    updated_prod = repo.find_by_sku("SKU-SPIKE-02")
    assert updated_prod["quantity"] == initial_qty + ordered_qty


def test_replenishment_api_routes(client, test_db_path):
    """Verifies REST endpoints for ROP, EOQ, recommendations, and PO workflows."""
    repo = ProductRepository(db_path=test_db_path)
    fast_prod = repo.find_by_sku("SKU-FAST-01")

    # 1. GET ROP
    res1 = client.get(f"/api/replenishment/rop/{fast_prod['id']}?service_level=0.95")
    assert res1.status_code == 200
    assert res1.get_json()["data"]["reorder_point"] > 0

    # 2. GET EOQ
    res2 = client.get(f"/api/replenishment/eoq/{fast_prod['id']}")
    assert res2.status_code == 200
    assert res2.get_json()["data"]["optimized_order_quantity"] >= 1

    # 3. GET Recommendations
    res3 = client.get("/api/replenishment/recommendations")
    assert res3.status_code == 200
    recs_json = res3.get_json()["data"]["recommendations"]
    assert len(recs_json) > 0

    # 4. POST Consolidate PO
    rec_ids = [r["id"] for r in recs_json[:2] if "id" in r]
    res4 = client.post(
        "/api/replenishment/purchase-orders/consolidate",
        json={"recommendation_ids": rec_ids, "notes": "Test PO"}
    )
    assert res4.status_code == 201
    created_pos = res4.get_json()["data"]["purchase_orders"]
    assert len(created_pos) >= 1
    po_id = created_pos[0]["id"]

    # 5. GET PO List
    res5 = client.get("/api/replenishment/purchase-orders")
    assert res5.status_code == 200
    assert res5.get_json()["data"]["count"] >= 1

    # 6. PATCH PO Status
    res6 = client.patch(
        f"/api/replenishment/purchase-orders/{po_id}/status",
        json={"status": "APPROVED"}
    )
    assert res6.status_code == 200
    assert res6.get_json()["data"]["current_status"] == "APPROVED"
