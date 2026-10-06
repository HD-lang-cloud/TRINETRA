from flask import Blueprint, request
from services.risk_service import RiskScoringEngine
from services.dna_service import InventoryDNAService
from services.anomaly_service import AnomalyDetectionEngine
from services.capital_service import CapitalIntelligenceService
from utils.data_seeder import seed_demo_dataset
from utils.errors import format_response, NotFoundError

intelligence_bp = Blueprint("intelligence", __name__)
risk_service = RiskScoringEngine()
dna_service = InventoryDNAService()
anomaly_service = AnomalyDetectionEngine()
capital_service = CapitalIntelligenceService()


@intelligence_bp.route("/api/risks", methods=["GET"])
def get_portfolio_risks():
    """
    Evaluates 8-dimensional operational risks across the entire inventory.
    Returns prioritized risk queue sorted by severity and financial exposure.
    """
    risks = risk_service.evaluate_portfolio()
    return format_response(
        data={"risks": risks, "count": len(risks)},
        message="Portfolio risk analysis completed successfully.",
        status_code=200
    )


@intelligence_bp.route("/api/risks/<int:product_id>", methods=["GET"])
def get_product_risk(product_id: int):
    """Retrieves 8-dimensional risk scores and supporting evidence for a single SKU."""
    risk_profile = risk_service.evaluate_product_risk(product_id)
    return format_response(
        data=risk_profile,
        message="Product risk profile evaluated successfully.",
        status_code=200
    )


@intelligence_bp.route("/api/dna/<int:product_id>", methods=["GET"])
def get_product_dna(product_id: int):
    """Calculates behavioral Inventory DNA: velocity, volatility, coverage, and classifications."""
    dna = dna_service.calculate_dna(product_id)
    return format_response(
        data=dna,
        message="Inventory DNA profile calculated successfully.",
        status_code=200
    )



@intelligence_bp.route("/api/anomalies", methods=["GET"])
def get_anomalies():
    """Scans for statistical demand outliers (Z-score, IQR) and bulk stock depletions."""
    anomalies = anomaly_service.scan_all_anomalies()
    return format_response(
        data={"anomalies": anomalies, "count": len(anomalies)},
        message="Operational anomaly scan completed.",
        status_code=200
    )


@intelligence_bp.route("/api/system/seed", methods=["POST"])
def trigger_seed():
    """Generates the reproducible 7-story demo dataset with 90-day demand histories."""
    data = request.get_json() or {}
    seed_val = int(data.get("seed", 42))
    result = seed_demo_dataset(seed=seed_val)
    return format_response(
        data=result,
        message="Demonstration dataset seeded successfully.",
        status_code=201
    )
