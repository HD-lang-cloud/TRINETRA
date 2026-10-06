"""
TRINETRA — Supply Network Topology & Bottleneck Endpoints (Phase 8, Spec §28, §29, §30)
Provides RESTful APIs for graph topology, bottleneck identification, subgraph traversal,
and node outage impact simulation.
"""

from flask import Blueprint, jsonify, request
from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = BASE_DIR / "backend"
for p in [str(BASE_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from services.network_service import SupplyNetworkService
from utils.logger import app_logger
from utils.errors import ValidationError, NotFoundError

network_bp = Blueprint("network", __name__, url_prefix="/api/network")
network_service = SupplyNetworkService()


@network_bp.route("/topology", methods=["GET"])
def get_topology():
    """
    Returns full multi-tier supply network topology including nodes, edges,
    centrality scores, and fragility indices (Spec §28, §30).
    """
    try:
        data = network_service.get_topology()
        return jsonify({
            "status": "success",
            "data": data
        }), 200
    except Exception as e:
        app_logger.error(f"Failed to compute network topology: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@network_bp.route("/bottlenecks", methods=["GET"])
def get_bottlenecks():
    """
    Returns identified network bottlenecks, single points of failure,
    and high-fragility nodes (Spec §29).
    """
    try:
        bottlenecks = network_service.get_bottlenecks()
        return jsonify({
            "status": "success",
            "data": {
                "bottlenecks": bottlenecks,
                "count": len(bottlenecks)
            }
        }), 200
    except Exception as e:
        app_logger.error(f"Failed to evaluate network bottlenecks: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@network_bp.route("/subgraph/<node_id>", methods=["GET"])
def get_subgraph(node_id: str):
    """
    Returns 2-hop upstream and downstream dependency cascade for a target node.
    """
    try:
        subgraph = network_service.get_subgraph(node_id)
        return jsonify({
            "status": "success",
            "data": subgraph
        }), 200
    except NotFoundError as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except Exception as e:
        app_logger.error(f"Failed to fetch subgraph for {node_id}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@network_bp.route("/simulate-outage", methods=["POST"])
def simulate_outage():
    """
    Simulates node removal / supplier failure and quantifies disruption blast radius (Spec §29).
    Request body: { "node_id": "SUP-1" }
    """
    payload = request.get_json(silent=True) or {}
    node_id = payload.get("node_id")

    if not node_id:
        return jsonify({
            "status": "error",
            "message": "Missing required field 'node_id'."
        }), 400

    try:
        impact = network_service.simulate_node_outage(node_id)
        return jsonify({
            "status": "success",
            "data": impact
        }), 200
    except NotFoundError as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except Exception as e:
        app_logger.error(f"Outage simulation failed for {node_id}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
