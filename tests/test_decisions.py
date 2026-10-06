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
from services.replenishment_service import ReplenishmentService
from services.decision_service import DecisionService
from utils.errors import ValidationError


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    """Creates a temporary isolated SQLite database file and seeds it with demo data."""
    temp_dir = tmp_path_factory.mktemp("trinetra_decisions")
    db_file = str(temp_dir / "test_decisions_trinetra.db")
    initialize_database(db_file)
    seed_demo_dataset(db_path=db_file, seed=42)
    # Generate initial replenishment recommendations
    rep_service = ReplenishmentService(db_path=db_file)
    rep_service.generate_recommendations(service_level=0.95)
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


def test_get_active_recommendation_cards(test_db_path):
    """Verifies recommendations contain WHAT, WHY, EVIDENCE, CONFIDENCE, ALTERNATIVES (Spec §25)."""
    service = DecisionService(db_path=test_db_path)
    cards = service.get_active_recommendations(status="PENDING")

    assert len(cards) >= 1
    first = cards[0]
    assert "what" in first
    assert "why" in first
    assert "evidence" in first
    assert "confidence_pct" in first
    assert "alternative_options" in first
    assert first["status"] == "PENDING"


def test_record_decision_approved(test_db_path):
    """Verifies APPROVE action logs decision, creates PO, and records outcome (Spec §26, §27)."""
    service = DecisionService(db_path=test_db_path)
    cards = service.get_active_recommendations(status="PENDING")
    target_rec = cards[0]

    result = service.record_decision(
        recommendation_id=target_rec["id"],
        decision_type="APPROVED",
        override_reason="Approved per standard replenishment policy",
        user_id=1
    )

    assert result["decision_type"] == "APPROVED"
    assert result["execution_status"] == "EXECUTED"
    assert result["stockout_avoided"] is True
    assert result["estimated_savings_inr"] > 0

    # Verify PO was created in database
    conn = get_db_connection(test_db_path)
    try:
        po = conn.execute(
            "SELECT * FROM purchase_orders WHERE notes LIKE ?",
            (f"%Decision #{result['decision_id']}%",)
        ).fetchone()
        assert po is not None
        assert po["status"] == "APPROVED"
    finally:
        conn.close()


def test_record_decision_modified_requires_reason(test_db_path):
    """Verifies that MODIFIED requires operational override reason and applies adjustments (Spec §26)."""
    service = DecisionService(db_path=test_db_path)
    cards = service.get_active_recommendations(status="PENDING")
    assert len(cards) >= 1
    target_rec = cards[0]

    # Empty reason must raise ValidationError
    with pytest.raises(ValidationError):
        service.record_decision(
            recommendation_id=target_rec["id"],
            decision_type="MODIFIED",
            override_reason="",  # Missing reason
            modified_params={"quantity": 25}
        )

    # Valid modification with reason
    result = service.record_decision(
        recommendation_id=target_rec["id"],
        decision_type="MODIFIED",
        override_reason="Budget constrained; scaling down order to 25 units",
        modified_params={"quantity": 25},
        user_id=1
    )

    assert result["decision_type"] == "MODIFIED"
    assert result["executed_quantity"] == 25
    assert result["execution_status"] == "EXECUTED"


def test_record_decision_rejected_requires_reason(test_db_path):
    """Verifies that REJECTED requires operational reason and prevents PO creation (Spec §26)."""
    service = DecisionService(db_path=test_db_path)
    cards = service.get_active_recommendations(status="PENDING")
    if not cards:
        # Generate another recommendation
        rep_service = ReplenishmentService(db_path=test_db_path)
        rep_service.generate_recommendations(service_level=0.90)
        cards = service.get_active_recommendations(status="PENDING")

    target_rec = cards[0]

    # Empty reason fails
    with pytest.raises(ValidationError):
        service.record_decision(
            recommendation_id=target_rec["id"],
            decision_type="REJECTED",
            override_reason="No"  # Too short
        )

    # Valid rejection
    result = service.record_decision(
        recommendation_id=target_rec["id"],
        decision_type="REJECTED",
        override_reason="Product scheduled for phase-out next month; do not replenish",
        user_id=1
    )

    assert result["decision_type"] == "REJECTED"
    assert result["executed_quantity"] == 0
    assert result["stockout_avoided"] is False


def test_closed_loop_outcome_verification(test_db_path):
    """Verifies recording outcome verification in decision_outcomes table (Spec §27)."""
    service = DecisionService(db_path=test_db_path)
    ledger = service.get_decision_ledger(limit=1)
    assert len(ledger) >= 1
    d_id = ledger[0]["decision_id"]

    res = service.record_outcome_verification(
        decision_id=d_id,
        observed_result="Delivery arrived on schedule. Zero stockout days experienced.",
        stockout_avoided=True,
        savings_amount=45000.0
    )

    assert res["status"] == "VERIFIED"
    assert res["stockout_avoided"] is True
    assert res["savings_amount"] == 45000.0


def test_governance_metrics_scorecard(test_db_path):
    """Verifies calculation of governance compliance scorecard (Spec §27, §34)."""
    service = DecisionService(db_path=test_db_path)
    metrics = service.get_governance_metrics()

    assert metrics["total_decisions"] >= 3
    assert metrics["approval_rate_pct"] >= 0.0
    assert metrics["modification_rate_pct"] >= 0.0
    assert metrics["rejection_rate_pct"] >= 0.0
    assert metrics["stockouts_avoided_count"] >= 1


def test_decisions_rest_api_endpoints(client, test_db_path):
    """Verifies REST endpoints for recommendations, decision actions, and ledger."""
    # 1. GET Recommendations
    res1 = client.get("/api/decisions/recommendations")
    assert res1.status_code == 200
    assert "recommendations" in res1.get_json()["data"]

    # 2. GET Decision Ledger
    res2 = client.get("/api/decisions/ledger")
    assert res2.status_code == 200
    assert res2.get_json()["data"]["count"] >= 1

    # 3. GET Governance Metrics
    res3 = client.get("/api/decisions/governance")
    assert res3.status_code == 200
    gov = res3.get_json()["data"]
    assert gov["total_decisions"] >= 1
    assert "breakdown" in gov
