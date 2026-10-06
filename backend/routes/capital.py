"""
TRINETRA — Working Capital Optimization & Rebalancing Routes (Phase 9, Spec §31, §32, §33)
Provides RESTful endpoints for Working Capital Pareto velocity analytics,
multi-echelon buffer rebalancing, dead stock reclamation playbooks, and holding cost sensitivity.
"""

from flask import Blueprint, jsonify, request
from pathlib import Path
from typing import Optional
import sys

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = BASE_DIR / "backend"
for p in [str(BASE_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from services.capital_optimizer_service import CapitalOptimizerService
from services.capital_service import CapitalIntelligenceService
from utils.logger import app_logger

capital_bp = Blueprint("capital_optimization", __name__, url_prefix="/api/capital")
optimizer_service = CapitalOptimizerService()
intelligence_service = CapitalIntelligenceService()


@capital_bp.route("", methods=["GET"])
def get_capital_overview():
    """
    Overview endpoint preserving Phase 3/8 behavior: returns capital distribution
    and the TRINETRA Resilience Index.
    """
    try:
        breakdown = intelligence_service.get_capital_breakdown()
        resilience = intelligence_service.calculate_resilience_index()
        return jsonify({
            "status": "success",
            "message": "Capital intelligence and resilience index retrieved.",
            "data": {
                "capital": breakdown,
                "resilience": resilience,
                **breakdown
            }
        }), 200
    except Exception as e:
        app_logger.error(f"Failed to fetch capital overview: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@capital_bp.route("/analytics", methods=["GET"])
def get_pareto_velocity_analytics():
    """
    Computes working capital Pareto curve, ITR turnover ratios, DSI,
    and Gini coefficient of capital concentration (Spec §31).
    """
    try:
        data = optimizer_service.get_pareto_and_velocity_analytics()
        return jsonify({
            "status": "success",
            "data": data
        }), 200
    except Exception as e:
        app_logger.error(f"Failed to compute capital analytics: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@capital_bp.route("/rebalance", methods=["POST"])
def rebalance_portfolio_buffers():
    """
    Calculates multi-echelon buffer rebalancing (Spec §32).
    Quantifies capital releases from overstock vs. capital injections to achieve target service level.
    Request body: { "budget_ceiling_inr": 50000, "service_level": 0.95 }
    """
    payload = request.get_json(silent=True) or {}
    budget_ceiling = payload.get("budget_ceiling_inr")
    service_level = float(payload.get("service_level", 0.95))

    if budget_ceiling is not None:
        try:
            budget_ceiling = float(budget_ceiling)
        except ValueError:
            budget_ceiling = None

    try:
        data = optimizer_service.rebalance_portfolio_buffers(
            budget_ceiling_inr=budget_ceiling,
            service_level=service_level
        )
        return jsonify({
            "status": "success",
            "data": data
        }), 200
    except Exception as e:
        app_logger.error(f"Failed to compute portfolio rebalance: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@capital_bp.route("/dead-stock-reclamation", methods=["GET"])
def get_dead_stock_reclamation():
    """
    Scans for dead stock and evaluates 4 structured reclamation strategies (Spec §33):
    Markdown, Buyback, Bundling, Scrap.
    """
    holding_rate = request.args.get("holding_cost_rate", default=0.20, type=float)

    try:
        data = optimizer_service.get_dead_stock_reclamation_playbook(holding_cost_rate=holding_rate)
        return jsonify({
            "status": "success",
            "data": data
        }), 200
    except Exception as e:
        app_logger.error(f"Failed to evaluate dead stock reclamation: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@capital_bp.route("/sensitivity", methods=["POST"])
def evaluate_holding_cost_sensitivity():
    """
    Evaluates liquidity sensitivity across varying annual holding cost rates (15% to 30%).
    Request body: { "rates": [0.15, 0.20, 0.25, 0.30] }
    """
    payload = request.get_json(silent=True) or {}
    rates = payload.get("rates")

    try:
        data = optimizer_service.evaluate_holding_cost_sensitivity(rates=rates)
        return jsonify({
            "status": "success",
            "data": data
        }), 200
    except Exception as e:
        app_logger.error(f"Failed to compute holding cost sensitivity: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
