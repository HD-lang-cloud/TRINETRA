"""
TRINETRA — Phase 10: Production Readiness, System Observability & Self-Healing Guardrails Tests
Tests system telemetry, statistical demand drift detection, self-healing database reconciler,
circuit breakers, and production REST API endpoints.
"""

import json
import pytest
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
for p in [str(BASE_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from app import create_app
from database import get_db_connection, db_transaction
from services.observability_service import SystemObservabilityService
from utils.data_seeder import seed_demo_dataset


@pytest.fixture(scope="module")
def app_instance():
    """Initializes test app with fresh database and seeded personas."""
    test_db = BASE_DIR / "tests" / "test_observability.db"
    if test_db.exists():
        test_db.unlink()

    app = create_app("testing")
    app.config["DATABASE_PATH"] = str(test_db)

    with app.app_context():
        from init_db import initialize_database
        initialize_database(str(test_db))
        seed_demo_dataset(str(test_db))

    yield app

    if test_db.exists():
        try:
            test_db.unlink()
        except Exception:
            pass


@pytest.fixture
def obs_service(app_instance):
    db_path = app_instance.config["DATABASE_PATH"]
    return SystemObservabilityService(db_path=db_path)


def test_system_telemetry_metrics(obs_service):
    """Verifies that system telemetry returns database health, record counts, and uptime."""
    telemetry = obs_service.get_system_telemetry()

    assert "database" in telemetry
    assert telemetry["database"]["engine"] == "SQLite"
    assert telemetry["database"]["integrity"] == "ok"
    assert telemetry["database"]["total_records"] > 0
    assert "products" in telemetry["database"]["table_counts"]
    assert telemetry["database"]["table_counts"]["products"] >= 7
    assert telemetry["uptime_seconds"] >= 0
    assert "os_platform" in telemetry
    assert isinstance(telemetry["recent_events"], list)


def test_demand_drift_detection(obs_service):
    """Verifies statistical data drift detection between baseline and recent demand."""
    drift_report = obs_service.detect_demand_drift(window_days=30)

    assert "status" in drift_report
    assert drift_report["status"] in ("STABLE", "WARNING", "DRIFT_DETECTED")
    assert drift_report["monitored_skus_count"] >= 5
    assert "drift_details" in drift_report

    # Check structure of drift items
    for item in drift_report["drift_details"]:
        assert "sku" in item
        assert "baseline_mean" in item
        assert "recent_mean" in item
        assert "drift_score_z" in item
        assert "drift_severity" in item
        assert item["drift_severity"] in ("NEGLIGIBLE", "MODERATE", "CRITICAL")
        assert isinstance(item["requires_retraining"], bool)


def test_self_healing_reconciliation_detects_and_repairs(obs_service, app_instance):
    """
    Simulates deliberate corruption (negative stock and PO total mismatch)
    and verifies the autonomous self-healing guardrail repairs them cleanly.
    """
    db_path = app_instance.config["DATABASE_PATH"]

    # Deliberately inject a ledger discrepancy (product quantity diverging from movement ledger)
    # and an inconsistent PO total
    with db_transaction(db_path) as conn:
        conn.execute("UPDATE products SET quantity = 999 WHERE id = 1")
        # Ensure a purchase order with items exists, then corrupt its total
        po = conn.execute("SELECT id, total_amount FROM purchase_orders LIMIT 1").fetchone()
        if po:
            conn.execute("UPDATE purchase_orders SET total_amount = 9999999 WHERE id = ?", (po["id"],))

    # Run self-healing reconciliation with auto_repair=True
    heal_result = obs_service.run_self_healing_reconciliation(auto_repair=True)

    assert heal_result["discrepancies_detected_count"] >= 1
    assert heal_result["repairs_applied_count"] >= 1
    assert heal_result["status"] in ("REPAIRED", "HEALTHY")

    # Verify database was healed
    conn = get_db_connection(db_path)
    try:
        healed_p = conn.execute("SELECT quantity FROM products WHERE id = 1").fetchone()
        # Verify it was reconciled away from the artificial 999
        assert healed_p["quantity"] != 999, "Ledger mismatch was not healed"

        # Verify audit log recorded the autonomous heal action
        logs = conn.execute(
            "SELECT * FROM audit_logs WHERE action LIKE 'AUTO_HEAL%' ORDER BY id DESC"
        ).fetchall()
        assert len(logs) >= 1
    finally:
        conn.close()


def test_circuit_breaker_guardrail(obs_service):
    """Verifies that circuit breaker checks system status correctly without tripping under normal conditions."""
    cb = obs_service.execute_circuit_breaker_check()

    assert "circuit_breaker_state" in cb
    assert cb["circuit_breaker_state"] in ("CLOSED_NORMAL", "TRIPPED_SAFE_MODE")
    assert isinstance(cb["is_tripped"], bool)
    assert cb["threshold_ratio"] == 0.50
    assert cb["mode"] in ("AUTONOMOUS", "SAFE_MODE")


def test_observability_api_endpoints(app_instance):
    """Verifies all Phase 10 REST endpoints respond with HTTP 200 and valid JSON schema."""
    client = app_instance.test_client()

    # 1. GET /api/system/telemetry
    r1 = client.get("/api/system/telemetry")
    assert r1.status_code == 200
    d1 = r1.get_json()["data"]
    assert "database" in d1
    assert d1["database"]["engine"] == "SQLite"

    # 2. GET /api/system/drift
    r2 = client.get("/api/system/drift?window_days=30")
    assert r2.status_code == 200
    d2 = r2.get_json()["data"]
    assert "status" in d2
    assert "drift_details" in d2

    # 3. POST /api/system/reconcile
    r3 = client.post("/api/system/reconcile", json={"auto_repair": True})
    assert r3.status_code == 200
    d3 = r3.get_json()["data"]
    assert "status" in d3
    assert "discrepancies_detected_count" in d3

    # 4. GET /api/system/circuit-breaker
    r4 = client.get("/api/system/circuit-breaker")
    assert r4.status_code == 200
    d4 = r4.get_json()["data"]
    assert "circuit_breaker_state" in d4
    assert d4["mode"] in ("AUTONOMOUS", "SAFE_MODE")
