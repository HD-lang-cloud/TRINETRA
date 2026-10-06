"""
TRINETRA — Supply Network Graph & Multitier Topology Engine Tests (Phase 8, Spec §28, §29, §30)
Verifies multi-tier directed graph construction, Brandes betweenness centrality,
Single Point of Failure (SPOF) detection, blast radius impact, and outage simulation.
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
from services.network_service import SupplyNetworkService, DirectedSupplyGraph


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    """Creates a temporary isolated SQLite database file and seeds it with demo data."""
    temp_dir = tmp_path_factory.mktemp("trinetra_network")
    db_file = str(temp_dir / "test_network_trinetra.db")
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


def test_directed_graph_brandes_betweenness():
    """Unit test: verifies pure Python Brandes betweenness centrality on canonical diamond graph."""
    g = DirectedSupplyGraph()
    # Diamond graph: A -> B, A -> C, B -> D, C -> D
    g.add_node("A", "Source", "TIER_2_SUPPLIER")
    g.add_node("B", "Mid1", "TIER_1_SUPPLIER")
    g.add_node("C", "Mid2", "TIER_1_SUPPLIER")
    g.add_node("D", "Sink", "PRODUCT")

    g.add_edge("A", "B", "FEEDS")
    g.add_edge("A", "C", "FEEDS")
    g.add_edge("B", "D", "SUPPLIES")
    g.add_edge("C", "D", "SUPPLIES")

    bc = g.compute_betweenness_centrality()
    assert bc["A"] == 0.0  # Endpoints have 0 betweenness in standard betweenness definition
    assert bc["D"] == 0.0
    assert bc["B"] > 0.0   # Intermediaries carry shortest paths
    assert bc["C"] > 0.0
    assert bc["B"] == bc["C"]  # Symmetric diamond


def test_network_graph_construction(test_db_path):
    """Verifies construction of multitier topology from database tables (Spec §28)."""
    service = SupplyNetworkService(db_path=test_db_path)
    topology = service.get_topology()

    summary = topology["summary"]
    nodes = topology["nodes"]
    edges = topology["edges"]

    assert summary["total_nodes"] >= 15
    assert summary["total_edges"] >= 15
    assert summary["tier2_suppliers_count"] >= 3
    assert summary["tier1_suppliers_count"] >= 5
    assert summary["products_count"] >= 7
    assert summary["locations_count"] >= 3

    # Verify node types
    node_types = {n["node_type"] for n in nodes}
    assert "TIER_2_SUPPLIER" in node_types
    assert "TIER_1_SUPPLIER" in node_types
    assert "PRODUCT" in node_types
    assert "LOCATION" in node_types

    # Verify edge types
    edge_types = {e["edge_type"] for e in edges}
    assert "FEEDS_RAW_MATERIAL" in edge_types
    assert "SUPPLIES_COMPONENT" in edge_types
    assert "STORED_AT" in edge_types


def test_spof_detection_and_centrality_metrics(test_db_path):
    """Verifies Single Point of Failure (SPOF) detection and metrics (Spec §29)."""
    service = SupplyNetworkService(db_path=test_db_path)
    topology = service.get_topology()
    nodes = topology["nodes"]

    # Monopoly Specialty Alloys should be detected as SPOF for SKU-SPOF-03
    monopoly_node = next((n for n in nodes if "Monopoly Specialty Alloys" in n["label"]), None)
    assert monopoly_node is not None
    assert monopoly_node["is_spof"] is True
    assert monopoly_node["blast_radius_skus"] >= 1
    assert monopoly_node["fragility_index"] > 50.0

    # Kyoto Sensors should be detected as SPOF for SKU-SPIKE-02
    kyoto_node = next((n for n in nodes if "Kyoto Sensors" in n["label"]), None)
    assert kyoto_node is not None
    assert kyoto_node["is_spof"] is True
    assert kyoto_node["blast_radius_skus"] >= 1

    # Verify summary SPOF count
    assert topology["summary"]["spof_nodes_count"] >= 2


def test_bottlenecks_ranking(test_db_path):
    """Verifies bottleneck ranking prioritizes SPOFs and high fragility nodes (Spec §29)."""
    service = SupplyNetworkService(db_path=test_db_path)
    bottlenecks = service.get_bottlenecks()

    assert len(bottlenecks) >= 2
    # First bottleneck should be an active SPOF
    assert bottlenecks[0]["is_spof"] is True
    assert bottlenecks[0]["fragility_index"] >= bottlenecks[-1]["fragility_index"]


def test_subgraph_traversal(test_db_path):
    """Verifies 2-hop upstream and downstream dependency extraction for a node."""
    service = SupplyNetworkService(db_path=test_db_path)
    topology = service.get_topology()
    nodes = topology["nodes"]

    apex_node = next(n for n in nodes if "Apex Semiconductor" in n["label"])
    subgraph = service.get_subgraph(apex_node["id"])

    assert subgraph["root_node_id"] == apex_node["id"]
    assert subgraph["upstream_count"] >= 1    # Global Silicon Crystals GmbH
    assert subgraph["downstream_count"] >= 1  # SKU-FAST-01 & Warehouses
    assert len(subgraph["nodes"]) >= 3
    assert len(subgraph["edges"]) >= 2


def test_simulate_node_outage_impact(test_db_path):
    """Verifies outage simulation quantifies severed SKUs and revenue exposure (Spec §29)."""
    service = SupplyNetworkService(db_path=test_db_path)
    topology = service.get_topology()
    nodes = topology["nodes"]

    # 1. Outage of Monopoly Specialty Alloys (Sole supplier of SKU-SPOF-03)
    monopoly = next(n for n in nodes if "Monopoly Specialty Alloys" in n["label"])
    impact1 = service.simulate_node_outage(monopoly["id"])

    assert impact1["impact_summary"]["severed_skus_count"] >= 1
    assert impact1["impact_summary"]["total_revenue_exposure_inr"] > 0
    assert impact1["impact_summary"]["severity"] == "CRITICAL"
    assert len(impact1["severed_skus"]) >= 1
    assert any("SKU-SPOF-03" in s["sku"] for s in impact1["severed_skus"])

    # 2. Outage of Apex Semiconductor Corp (Dual-sourced with Vertex for SKU-FAST-01)
    apex = next(n for n in nodes if "Apex Semiconductor" in n["label"])
    impact2 = service.simulate_node_outage(apex["id"])

    # SKU-FAST-01 has Vertex Precision Foundry as backup, so it should be degraded but not severed
    assert any("SKU-FAST-01" in d["sku"] for d in impact2["degraded_skus"])


def test_network_rest_api_endpoints(client, test_db_path):
    """Verifies all REST API routes for topology, bottlenecks, subgraph, and outage simulation."""
    # 1. GET /api/network/topology
    res1 = client.get("/api/network/topology")
    assert res1.status_code == 200
    data1 = res1.get_json()["data"]
    assert "summary" in data1
    assert "nodes" in data1
    assert "edges" in data1

    # 2. GET /api/network/bottlenecks
    res2 = client.get("/api/network/bottlenecks")
    assert res2.status_code == 200
    data2 = res2.get_json()["data"]
    assert "bottlenecks" in data2
    assert len(data2["bottlenecks"]) >= 2

    # 3. GET /api/network/subgraph/<node_id>
    test_node_id = data1["nodes"][0]["id"]
    res3 = client.get(f"/api/network/subgraph/{test_node_id}")
    assert res3.status_code == 200
    data3 = res3.get_json()["data"]
    assert data3["root_node_id"] == test_node_id

    # 4. POST /api/network/simulate-outage
    res4 = client.post("/api/network/simulate-outage", json={"node_id": test_node_id})
    assert res4.status_code == 200
    data4 = res4.get_json()["data"]
    assert "impact_summary" in data4
    assert "recommended_mitigation" in data4
