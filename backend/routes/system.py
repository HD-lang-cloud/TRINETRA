import time
from datetime import datetime, timezone
from flask import Blueprint, current_app, request
from database import get_db_connection
from repositories.product_repository import ProductRepository
from utils.errors import format_response

system_bp = Blueprint("system", __name__)
START_TIME = time.time()


@system_bp.route("/api/system/health", methods=["GET"])
def health_check():
    """
    Comprehensive health check verifying database connectivity,
    environment configuration, and operational uptime.
    """
    db_healthy = False
    db_version = "Unknown"
    table_count = 0

    try:
        conn = get_db_connection()
        cursor = conn.execute("SELECT sqlite_version()")
        db_version = cursor.fetchone()[0]

        cursor = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        table_count = cursor.fetchone()[0]
        conn.close()
        db_healthy = True
    except Exception as e:
        current_app.logger.error(f"Health check database failure: {e}")

    uptime_seconds = int(time.time() - START_TIME)
    status = "healthy" if db_healthy else "degraded"

    data = {
        "status": status,
        "platform": "TRINETRA",
        "descriptor": "AI-Native Inventory Resilience & Decision Intelligence Platform",
        "tagline": "SEE. FORESEE. PREPARE.",
        "version": "1.0.0",
        "uptime_seconds": uptime_seconds,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": {
            "connected": db_healthy,
            "engine": "SQLite",
            "version": db_version,
            "tables_initialized": table_count
        },
        "environment": current_app.config.get("ENV", "development"),
        "llm_provider": current_app.config.get("LLM_PROVIDER", "mock")
    }

    return format_response(
        data=data,
        message="TRINETRA system is operational.",
        status_code=200 if db_healthy else 503
    )


@system_bp.route("/api/system/pulse", methods=["GET"])
def system_pulse():
    """
    High-level operational pulse providing immediate inventory metrics:
    total SKUs, total units, total capital value, and low stock count.
    """
    product_repo = ProductRepository()
    summary = product_repo.get_inventory_summary()

    return format_response(
        data=summary,
        message="Inventory pulse metrics retrieved successfully.",
        status_code=200
    )


@system_bp.route("/api/system/telemetry", methods=["GET"])
def system_telemetry():
    """
    Detailed system telemetry: database sizes, record counts across all 17 tables,
    uptime, SQLite pragma integrity, and recent system event logs (Spec §36).
    """
    from services.observability_service import SystemObservabilityService
    obs_service = SystemObservabilityService()
    data = obs_service.get_system_telemetry()

    return format_response(
        data=data,
        message="System telemetry metrics retrieved successfully.",
        status_code=200
    )


@system_bp.route("/api/system/drift", methods=["GET"])
def demand_drift_detection():
    """
    Data drift analysis across all product demand histories (Spec §36).
    Detects statistical distribution shift between baseline and recent demand.
    """
    from services.observability_service import SystemObservabilityService
    obs_service = SystemObservabilityService()
    window = int(request.args.get("window_days", 30))
    data = obs_service.detect_demand_drift(window_days=window)

    return format_response(
        data=data,
        message="Demand drift analysis complete.",
        status_code=200
    )


@system_bp.route("/api/system/reconcile", methods=["POST"])
def run_self_healing_reconciliation():
    """
    Autonomous Self-Healing Guardrail (Spec §36):
    Audits and automatically repairs 4 core database invariants:
    1. Stock ledger integrity (quantity == balance_after)
    2. Non-negative stock constraints
    3. Purchase order subtotal sums
    4. Location inventory mappings
    """
    from services.observability_service import SystemObservabilityService
    obs_service = SystemObservabilityService()
    payload = request.get_json(silent=True) or {}
    auto_repair = payload.get("auto_repair", True)

    data = obs_service.run_self_healing_reconciliation(auto_repair=auto_repair)

    return format_response(
        data=data,
        message=f"Self-healing audit complete. Found {data['discrepancies_detected_count']} issues, applied {data['repairs_applied_count']} repairs.",
        status_code=200
    )


@system_bp.route("/api/system/circuit-breaker", methods=["GET"])
def circuit_breaker_status():
    """
    Autonomous Circuit Breaker Guardrail:
    Checks anomaly densities and stockout crisis ratios to verify system operational safety.
    """
    from services.observability_service import SystemObservabilityService
    obs_service = SystemObservabilityService()
    data = obs_service.execute_circuit_breaker_check()

    return format_response(
        data=data,
        message=f"Circuit breaker status: {data['circuit_breaker_state']}.",
        status_code=200
    )
