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
from database import get_db_connection


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    """Creates a temporary isolated SQLite database file for testing."""
    temp_dir = tmp_path_factory.mktemp("trinetra_core_inv")
    db_file = temp_dir / "test_core_trinetra.db"
    initialize_database(str(db_file))
    return str(db_file)


@pytest.fixture
def app(test_db_path, monkeypatch):
    """Creates a test Flask application configured to use the test database."""
    monkeypatch.setenv("DATABASE_PATH", test_db_path)
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    app_instance = create_app("testing")
    app_instance.config["DATABASE_PATH"] = test_db_path
    return app_instance


@pytest.fixture
def client(app):
    return app.test_client()


def test_product_lifecycle_crud(client):
    """Tests product creation, retrieval, update, and soft deletion."""
    # 1. Create product
    create_res = client.post("/api/products", json={
        "sku": "SKU-AUTO-01",
        "name": "Microcontroller Unit",
        "category": "Semiconductors",
        "quantity": 100,
        "price": 450.0,
        "reorder_threshold": 25,
        "target_stock_level": 200,
        "description": "High performance 32-bit MCU"
    })
    assert create_res.status_code == 201
    prod = create_res.get_json()["data"]
    prod_id = prod["id"]
    assert prod["sku"] == "SKU-AUTO-01"
    assert prod["quantity"] == 100

    # 2. Get product details
    detail_res = client.get(f"/api/products/{prod_id}")
    assert detail_res.status_code == 200
    detail_data = detail_res.get_json()["data"]
    assert detail_data["product"]["name"] == "Microcontroller Unit"
    # Opening stock movement should have been automatically recorded
    assert len(detail_data["recent_movements"]) >= 1
    assert detail_data["recent_movements"][0]["movement_type"] == "PURCHASE"

    # 3. Update product metadata
    update_res = client.put(f"/api/products/{prod_id}", json={
        "price": 480.0,
        "reorder_threshold": 30
    })
    assert update_res.status_code == 200
    updated_prod = update_res.get_json()["data"]
    assert updated_prod["price"] == 480.0
    assert updated_prod["reorder_threshold"] == 30

    # 4. Attempt direct quantity mutation via PUT (MUST BE REJECTED)
    invalid_put = client.put(f"/api/products/{prod_id}", json={
        "quantity": 500
    })
    assert invalid_put.status_code == 400
    assert "Direct quantity modification is disallowed" in invalid_put.get_json()["error"]["message"]

    # 5. Soft delete product
    del_res = client.delete(f"/api/products/{prod_id}")
    assert del_res.status_code == 200
    assert del_res.get_json()["data"]["status"] == "DISCONTINUED"


def test_stock_movement_deduction_and_negative_inventory_prevention(client):
    """
    Critical Invariant Test:
    - Normal sales decrement stock and update ledger.
    - Attempting a sale exceeding current balance is strictly blocked (negative inventory prevented).
    """
    # Create product with 50 units
    create_res = client.post("/api/products", json={
        "sku": "SKU-TEST-STOCKOUT",
        "name": "Safety Valve",
        "category": "Mechanical",
        "quantity": 50,
        "price": 1200.0,
        "reorder_threshold": 10
    })
    prod_id = create_res.get_json()["data"]["id"]

    # Execute valid sale of 20 units
    sale_res = client.post("/api/movements", json={
        "product_id": prod_id,
        "movement_type": "SALE",
        "quantity": 20,
        "reason": "Fulfilled Customer Order #SO-1092"
    })
    assert sale_res.status_code == 201
    sale_data = sale_res.get_json()["data"]
    assert sale_data["product"]["quantity"] == 30
    assert sale_data["movement"]["balance_after"] == 30
    assert sale_data["movement"]["quantity_change"] == -20

    # Attempt EXCESSIVE sale of 35 units (current balance is only 30) -> MUST FAIL
    overdraw_res = client.post("/api/movements", json={
        "product_id": prod_id,
        "movement_type": "SALE",
        "quantity": 35,
        "reason": "Attempting overdrawn order"
    })
    assert overdraw_res.status_code == 400
    error_msg = overdraw_res.get_json()["error"]["message"]
    assert "Insufficient stock" in error_msg
    assert "Negative inventory is strictly prohibited" in error_msg

    # Verify inventory balance remained strictly 30 (zero state mutation on failure)
    verify_res = client.get(f"/api/products/{prod_id}")
    assert verify_res.get_json()["data"]["product"]["quantity"] == 30


def test_stock_movement_types_and_auditability(client, test_db_path):
    """Tests various movement types (DAMAGE, PURCHASE, RETURN) and verifies audit logs."""
    create_res = client.post("/api/products", json={
        "sku": "SKU-AUDIT-01",
        "name": "Precision Bearings",
        "category": "Hardware",
        "quantity": 10,
        "price": 250.0,
        "reorder_threshold": 5
    })
    prod_id = create_res.get_json()["data"]["id"]

    # Record DAMAGE
    client.post("/api/movements", json={
        "product_id": prod_id,
        "movement_type": "DAMAGE",
        "quantity": 2,
        "reason": "Damaged in transit from loading dock"
    })

    # Record PURCHASE
    client.post("/api/movements", json={
        "product_id": prod_id,
        "movement_type": "PURCHASE",
        "quantity": 15,
        "reason": "Received PO #PO-8812"
    })

    # Check movement history
    mov_res = client.get(f"/api/movements?product_id={prod_id}")
    assert mov_res.status_code == 200
    movements = mov_res.get_json()["data"]["movements"]
    types = [m["movement_type"] for m in movements]
    assert "DAMAGE" in types
    assert "PURCHASE" in types

    # Verify audit_logs table contains records
    conn = get_db_connection(test_db_path)
    logs = conn.execute("SELECT * FROM audit_logs WHERE entity_id = ?", (prod_id,)).fetchall()
    conn.close()
    assert len(logs) >= 2


def test_supplier_registration_and_product_linking(client):
    """Tests supplier creation and linking to products with terms."""
    # 1. Register supplier
    supp_res = client.post("/api/suppliers", json={
        "name": "Apex Micro Devices",
        "contact_email": "orders@apexmicro.com",
        "lead_time_days": 10,
        "lead_time_variance": 1.5,
        "reliability_score": 0.94
    })
    assert supp_res.status_code == 201
    supp_id = supp_res.get_json()["data"]["id"]

    # 2. Create product
    prod_res = client.post("/api/products", json={
        "sku": "SKU-SUPP-LINK",
        "name": "FPGA Accelerator Board",
        "category": "Electronics",
        "quantity": 5,
        "price": 8500.0,
        "reorder_threshold": 2
    })
    prod_id = prod_res.get_json()["data"]["id"]

    # 3. Link supplier to product
    link_res = client.post(f"/api/suppliers/{supp_id}/products", json={
        "product_id": prod_id,
        "unit_cost": 6200.0,
        "moq": 10,
        "supplier_lead_time_days": 12,
        "is_primary": True
    })
    assert link_res.status_code == 201

    # 4. Verify product details list the supplier
    detail_res = client.get(f"/api/products/{prod_id}")
    suppliers = detail_res.get_json()["data"]["suppliers"]
    assert len(suppliers) == 1
    assert suppliers[0]["supplier_name"] == "Apex Micro Devices"
    assert suppliers[0]["unit_cost"] == 6200.0
    assert suppliers[0]["is_primary"] == 1


def test_low_stock_filtering(client):
    """Tests the low_stock=true filter query."""
    client.post("/api/products", json={
        "sku": "SKU-LOW-01",
        "name": "Emergency Spare Kit",
        "category": "Maintenance",
        "quantity": 2,
        "price": 990.0,
        "reorder_threshold": 10
    })

    res = client.get("/api/products?low_stock=true")
    assert res.status_code == 200
    prods = res.get_json()["data"]["products"]
    assert any(p["sku"] == "SKU-LOW-01" for p in prods)
