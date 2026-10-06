import os
import sys
import pytest
from pathlib import Path

# Ensure backend directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
for p in [str(BASE_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app import create_app
from init_db import initialize_database
from database import get_db_connection
from repositories.product_repository import ProductRepository


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    """Creates a temporary isolated SQLite database file for testing."""
    temp_dir = tmp_path_factory.mktemp("trinetra_data")
    db_file = temp_dir / "test_trinetra.db"
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
    """Provides a test client for simulating HTTP requests."""
    return app.test_client()


def test_health_check_endpoint(client):
    """Verifies that /api/system/health returns 200 and operational database status."""
    response = client.get("/api/system/health")
    assert response.status_code == 200
    json_data = response.get_json()

    assert json_data["success"] is True
    assert json_data["data"]["status"] == "healthy"
    assert json_data["data"]["platform"] == "TRINETRA"
    assert json_data["data"]["database"]["connected"] is True
    assert json_data["data"]["database"]["tables_initialized"] >= 10


def test_root_serves_frontend_shell(client):
    """Verifies that visiting the root URL '/' serves the TRINETRA HTML workstation."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"TRINETRA" in response.data
    assert b"Command Center" in response.data


def test_system_pulse_endpoint(client):
    """Verifies that /api/system/pulse returns high-level inventory metrics."""
    response = client.get("/api/system/pulse")
    assert response.status_code == 200
    json_data = response.get_json()

    assert json_data["success"] is True
    assert "total_skus" in json_data["data"]
    assert "total_units" in json_data["data"]
    assert "total_capital_value" in json_data["data"]


def test_not_found_error_handler(client):
    """Verifies that accessing an unknown route returns standard 404 error envelope."""
    response = client.get("/api/unknown/endpoint")
    assert response.status_code == 404
    json_data = response.get_json()

    assert json_data["success"] is False
    assert json_data["error"]["code"] == "NOT_FOUND"


def test_product_validation_errors(client):
    """Verifies that negative prices or quantities are rejected with a 400 error."""
    # Test negative quantity
    res1 = client.post("/api/products", json={
        "name": "Invalid Widget",
        "category": "Hardware",
        "quantity": -5,
        "price": 100.0
    })
    assert res1.status_code == 400
    assert res1.get_json()["error"]["code"] == "VALIDATION_ERROR"

    # Test negative price
    res2 = client.post("/api/products", json={
        "name": "Invalid Widget",
        "category": "Hardware",
        "quantity": 10,
        "price": -50.0
    })
    assert res2.status_code == 400
    assert res2.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_product_repository_crud(test_db_path):
    """Tests the ProductRepository data abstraction directly."""
    repo = ProductRepository(db_path=test_db_path)
    
    # Insert test product
    product_data = {
        "sku": "TEST-SKU-999",
        "name": "Industrial Sensor",
        "category": "Electronics",
        "quantity": 25,
        "price": 1500.0,
        "reorder_threshold": 10,
        "target_stock_level": 60,
        "status": "ACTIVE"
    }
    prod_id = repo.insert(product_data)
    assert prod_id > 0

    # Retrieve and check
    fetched = repo.find_by_id(prod_id)
    assert fetched is not None
    assert fetched["sku"] == "TEST-SKU-999"
    assert fetched["quantity"] == 25
    assert fetched["price"] == 1500.0

    # Search
    results = repo.search_products(query="Sensor")
    assert len(results) >= 1
    assert results[0]["sku"] == "TEST-SKU-999"

    # Clean up
    assert repo.delete(prod_id) is True
    assert repo.find_by_id(prod_id) is None


def test_all_schema_tables_initialized(test_db_path):
    """Verifies that all 14 core TRINETRA tables exist in the initialized schema."""
    conn = get_db_connection(test_db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row["name"] for row in cursor.fetchall()}
    conn.close()

    required_tables = {
        "users", "categories", "suppliers", "locations", "products",
        "supplier_products", "inventory", "stock_movements", "demand_history",
        "forecasts", "forecast_metrics", "risk_scores", "anomalies",
        "scenarios", "scenario_results", "recommendations", "decisions",
        "decision_outcomes", "audit_logs", "system_events", "model_versions"
    }
    missing = required_tables - tables
    assert len(missing) == 0, f"Missing required database tables: {missing}"
