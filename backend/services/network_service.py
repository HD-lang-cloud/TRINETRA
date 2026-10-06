"""
TRINETRA — Supply Network Graph & Multitier Topology Engine (Phase 8, Spec §28, §29, §30)
Builds directed multitier supply network topologies, calculates graph centralities,
identifies bottlenecks & Single Points of Failure (SPOFs), and quantifies disruption blast radii.
"""

from collections import deque
from pathlib import Path
from typing import Dict, List, Set, Any, Optional, Tuple
import sys

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = BASE_DIR / "backend"
for p in [str(BASE_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from database import get_db_connection
from utils.logger import app_logger
from utils.errors import NotFoundError, ValidationError


class DirectedSupplyGraph:
    """
    Pure Python directed graph implementation optimized for supply chain networks.
    Supports Tier-2 -> Tier-1 -> Products -> Locations dependency flows and
    computes Brandes' betweenness centrality, degree metrics, and downstream blast radii.
    """

    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.adj: Dict[str, Set[str]] = {}       # node_id -> set of outgoing targets
        self.pred: Dict[str, Set[str]] = {}      # node_id -> set of incoming sources
        self.edges: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def add_node(self, node_id: str, label: str, node_type: str, **attributes) -> None:
        self.nodes[node_id] = {
            "id": node_id,
            "label": label,
            "node_type": node_type,
            **attributes
        }
        if node_id not in self.adj:
            self.adj[node_id] = set()
        if node_id not in self.pred:
            self.pred[node_id] = set()

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        lead_time_days: int = 7,
        reliability: float = 1.0,
        criticality: str = "MEDIUM",
        **attributes
    ) -> None:
        if source not in self.nodes or target not in self.nodes:
            return

        self.adj[source].add(target)
        self.pred[target].add(source)
        self.edges[(source, target)] = {
            "source": source,
            "target": target,
            "edge_type": edge_type,
            "lead_time_days": lead_time_days,
            "reliability": reliability,
            "criticality": criticality,
            **attributes
        }

    def compute_betweenness_centrality(self) -> Dict[str, float]:
        """
        Computes exact betweenness centrality for all nodes using Brandes' algorithm
        for unweighted directed networks. Normalizes to [0.0, 1.0].
        """
        cb: Dict[str, float] = {v: 0.0 for v in self.nodes}
        node_keys = list(self.nodes.keys())
        n = len(node_keys)
        if n <= 2:
            return cb

        for s in node_keys:
            # Single-source shortest paths via BFS
            stack: List[str] = []
            predecessors: Dict[str, List[str]] = {w: [] for w in node_keys}
            sigma: Dict[str, int] = {w: 0 for w in node_keys}
            sigma[s] = 1
            distance: Dict[str, int] = {w: -1 for w in node_keys}
            distance[s] = 0

            queue = deque([s])
            while queue:
                v = queue.popleft()
                stack.append(v)
                for w in self.adj.get(v, []):
                    # Path discovery
                    if distance[w] < 0:
                        queue.append(w)
                        distance[w] = distance[v] + 1
                    # Path counting
                    if distance[w] == distance[v] + 1:
                        sigma[w] += sigma[v]
                        predecessors[w].append(v)

            # Accumulation of pair dependencies
            delta: Dict[str, float] = {w: 0.0 for w in node_keys}
            while stack:
                w = stack.pop()
                for v in predecessors[w]:
                    if sigma[w] > 0:
                        delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
                if w != s:
                    cb[w] += delta[w]

        # Normalization factor for directed graphs: 1 / ((n-1)(n-2))
        scale = 1.0 / ((n - 1) * (n - 2)) if n > 2 else 1.0
        return {v: round(cb[v] * scale, 4) for v in self.nodes}

    def get_downstream_nodes(self, start_node_id: str) -> Set[str]:
        """BFS traversal following directed supply links downstream."""
        visited: Set[str] = set()
        queue = deque([start_node_id])
        while queue:
            curr = queue.popleft()
            for nxt in self.adj.get(curr, []):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        return visited

    def get_upstream_nodes(self, start_node_id: str) -> Set[str]:
        """BFS traversal following directed incoming dependencies upstream."""
        visited: Set[str] = set()
        queue = deque([start_node_id])
        while queue:
            curr = queue.popleft()
            for prev in self.pred.get(curr, []):
                if prev not in visited:
                    visited.add(prev)
                    queue.append(prev)
        return visited


class SupplyNetworkService:
    """
    Core engine managing supply network topology, multi-tier dependency mapping,
    bottleneck identification, and Single Point of Failure (SPOF) resilience analysis.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def build_network_graph(self) -> DirectedSupplyGraph:
        """
        Constructs the complete multi-tier network graph from SQLite database tables:
        - Tier 2 Suppliers (Raw material/component foundries)
        - Tier 1 Suppliers (Direct contract manufacturers)
        - Products (Finished catalog SKUs)
        - Locations (Warehouses & distribution centers)
        - Edges with lead-time, reliability, and criticality attributes
        """
        graph = DirectedSupplyGraph()
        conn = get_db_connection(self.db_path)
        try:
            # 1. Fetch Suppliers (Tier 1 & Tier 2)
            suppliers = conn.execute("SELECT * FROM suppliers").fetchall()
            for s in suppliers:
                tier = s["tier"] if "tier" in s.keys() else 1
                node_type = "TIER_2_SUPPLIER" if tier == 2 else "TIER_1_SUPPLIER"
                node_id = f"SUP-{s['id']}"
                graph.add_node(
                    node_id=node_id,
                    label=s["name"],
                    node_type=node_type,
                    db_id=s["id"],
                    tier=tier,
                    status=s["status"],
                    lead_time_days=s["lead_time_days"],
                    reliability_score=s["reliability_score"],
                    contact_email=s["contact_email"]
                )

            # 2. Fetch Products
            products = conn.execute("SELECT * FROM products").fetchall()
            for p in products:
                node_id = f"PROD-{p['id']}"
                graph.add_node(
                    node_id=node_id,
                    label=f"{p['sku']} ({p['name']})",
                    node_type="PRODUCT",
                    db_id=p["id"],
                    sku=p["sku"],
                    product_name=p["name"],
                    tier=0,
                    category=p["category"],
                    unit_price=float(p["price"]),
                    on_hand=int(p["quantity"]),
                    reorder_threshold=int(p["reorder_threshold"]),
                    target_stock_level=int(p["target_stock_level"]),
                    status=p["status"]
                )

            # 3. Fetch Locations
            locations = conn.execute("SELECT * FROM locations").fetchall()
            for loc in locations:
                node_id = f"LOC-{loc['id']}"
                graph.add_node(
                    node_id=node_id,
                    label=f"{loc['code']} ({loc['name']})",
                    node_type="LOCATION",
                    db_id=loc["id"],
                    tier=-1,
                    code=loc["code"],
                    location_type=loc["location_type"]
                )

            # 4. Edges: Tier 2 -> Tier 1 (Raw materials)
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='supplier_tier_dependencies'")
            if cursor.fetchone():
                tier_deps = conn.execute("SELECT * FROM supplier_tier_dependencies").fetchall()
                for dep in tier_deps:
                    src_id = f"SUP-{dep['tier2_supplier_id']}"
                    tgt_id = f"SUP-{dep['tier1_supplier_id']}"
                    graph.add_edge(
                        source=src_id,
                        target=tgt_id,
                        edge_type="FEEDS_RAW_MATERIAL",
                        material_name=dep["material_name"],
                        lead_time_days=dep["lead_time_days"],
                        criticality=dep["criticality"],
                        reliability=0.92
                    )

            # 5. Edges: Tier 1 -> Products (Finished SKU production)
            supp_prods = conn.execute(
                """
                SELECT sp.*, s.reliability_score, s.lead_time_days as supp_lead_time
                FROM supplier_products sp
                JOIN suppliers s ON sp.supplier_id = s.id
                """
            ).fetchall()
            for sp in supp_prods:
                src_id = f"SUP-{sp['supplier_id']}"
                tgt_id = f"PROD-{sp['product_id']}"
                graph.add_edge(
                    source=src_id,
                    target=tgt_id,
                    edge_type="SUPPLIES_COMPONENT",
                    lead_time_days=sp["supplier_lead_time_days"],
                    reliability=sp["reliability_score"],
                    is_primary=bool(sp["is_primary"]),
                    unit_cost=float(sp["unit_cost"]),
                    moq=int(sp["moq"]),
                    criticality="HIGH" if sp["is_primary"] else "MEDIUM"
                )

            # 6. Edges: Products -> Locations (Inventory storage)
            inv_rows = conn.execute("SELECT * FROM inventory").fetchall()
            for inv in inv_rows:
                src_id = f"PROD-{inv['product_id']}"
                tgt_id = f"LOC-{inv['location_id']}"
                graph.add_edge(
                    source=src_id,
                    target=tgt_id,
                    edge_type="STORED_AT",
                    stored_quantity=inv["quantity"],
                    lead_time_days=1,
                    reliability=1.0,
                    criticality="LOW"
                )

            return graph
        finally:
            conn.close()

    def get_topology(self) -> Dict[str, Any]:
        """
        Returns full multi-tier topology with enriched node metrics,
        centrality scores, fragility indices, and summary analytics (Spec §28, §30).
        """
        graph = self.build_network_graph()
        betweenness = graph.compute_betweenness_centrality()

        # Identify Single Points of Failure and calculate blast radii
        enriched_nodes: List[Dict[str, Any]] = []
        spof_count = 0
        total_fragility = 0.0

        for node_id, node in graph.nodes.items():
            in_deg = len(graph.pred.get(node_id, set()))
            out_deg = len(graph.adj.get(node_id, set()))
            deg = in_deg + out_deg
            bc_score = betweenness.get(node_id, 0.0)

            # Downstream reachability analysis
            downstream = graph.get_downstream_nodes(node_id)
            downstream_skus = [d for d in downstream if graph.nodes[d]["node_type"] == "PRODUCT"]
            blast_radius_skus = len(downstream_skus)

            # Calculate downstream inventory and revenue exposure
            exposure_inr = 0.0
            for d_sku_id in downstream_skus:
                sku_node = graph.nodes[d_sku_id]
                exposure_inr += sku_node.get("on_hand", 0) * sku_node.get("unit_price", 0.0)

            # Determine SPOF status
            is_spof = False
            if node["node_type"] in ("TIER_1_SUPPLIER", "TIER_2_SUPPLIER"):
                # Check if any downstream SKU has ONLY this supplier chain
                for d_sku_id in downstream_skus:
                    sku_suppliers = {
                        s for s in graph.pred.get(d_sku_id, set())
                        if graph.nodes[s]["node_type"] == "TIER_1_SUPPLIER"
                    }
                    if len(sku_suppliers) == 1 and (node_id in sku_suppliers or node_id in graph.get_upstream_nodes(list(sku_suppliers)[0])):
                        is_spof = True
                        break

            if is_spof:
                spof_count += 1

            # Compute Fragility Index (0 - 100)
            fragility = self._calculate_node_fragility(node, is_spof, blast_radius_skus, in_deg, out_deg)
            total_fragility += fragility

            enriched_nodes.append({
                **node,
                "in_degree": in_deg,
                "out_degree": out_deg,
                "degree": deg,
                "betweenness_centrality": bc_score,
                "is_spof": is_spof,
                "blast_radius_skus": blast_radius_skus,
                "revenue_exposure_inr": round(exposure_inr, 2),
                "fragility_index": round(fragility, 1)
            })

        # Enrich edges with single-source flags
        enriched_edges: List[Dict[str, Any]] = []
        for (src, tgt), edge_data in graph.edges.items():
            # If target is product and has only 1 incoming supplier
            tgt_suppliers = [
                s for s in graph.pred.get(tgt, set())
                if graph.nodes[s]["node_type"] == "TIER_1_SUPPLIER"
            ]
            is_single_src = len(tgt_suppliers) == 1

            enriched_edges.append({
                **edge_data,
                "id": f"e-{src}-{tgt}",
                "is_single_source": is_single_src
            })

        tier2_nodes = [n for n in enriched_nodes if n["node_type"] == "TIER_2_SUPPLIER"]
        tier1_nodes = [n for n in enriched_nodes if n["node_type"] == "TIER_1_SUPPLIER"]
        prod_nodes = [n for n in enriched_nodes if n["node_type"] == "PRODUCT"]
        loc_nodes = [n for n in enriched_nodes if n["node_type"] == "LOCATION"]

        avg_fragility = round(total_fragility / len(enriched_nodes), 1) if enriched_nodes else 0.0
        max_blast = max((n["blast_radius_skus"] for n in enriched_nodes), default=0)

        return {
            "summary": {
                "total_nodes": len(enriched_nodes),
                "total_edges": len(enriched_edges),
                "tier2_suppliers_count": len(tier2_nodes),
                "tier1_suppliers_count": len(tier1_nodes),
                "products_count": len(prod_nodes),
                "locations_count": len(loc_nodes),
                "spof_nodes_count": spof_count,
                "max_blast_radius_skus": max_blast,
                "mean_network_fragility": avg_fragility
            },
            "nodes": enriched_nodes,
            "edges": enriched_edges
        }

    def _calculate_node_fragility(
        self,
        node: Dict[str, Any],
        is_spof: bool,
        blast_radius: int,
        in_degree: int,
        out_degree: int
    ) -> float:
        """
        Calculates normalized node fragility index (0 - 100) based on:
        SPOF severity (40 pts), vendor reliability (25 pts), lead time (20 pts), and blast radius (15 pts).
        """
        score = 0.0

        if is_spof:
            score += 40.0

        if node["node_type"] in ("TIER_1_SUPPLIER", "TIER_2_SUPPLIER"):
            rel = node.get("reliability_score", 1.0)
            score += max(0.0, (1.0 - rel) * 100.0 * 0.25)

            lt = node.get("lead_time_days", 7)
            score += min(20.0, (lt / 45.0) * 20.0)

            score += min(15.0, (blast_radius / 5.0) * 15.0)

            if node.get("status") == "WARNING":
                score += 10.0
            elif node.get("status") == "SUSPENDED":
                score += 25.0

        elif node["node_type"] == "PRODUCT":
            # For products, fragility is high if single-sourced
            if in_degree <= 1:
                score += 35.0
            on_hand = node.get("on_hand", 0)
            target = node.get("target_stock_level", 50)
            if on_hand < (target * 0.3):
                score += 20.0

        return min(100.0, max(0.0, score))

    def get_bottlenecks(self) -> List[Dict[str, Any]]:
        """
        Identifies critical network bottlenecks and single points of failure (Spec §29).
        Sorted by fragility index and betweenness centrality.
        """
        topology = self.get_topology()
        nodes = topology["nodes"]

        # Filter for nodes that are either SPOFs or have elevated betweenness/fragility
        bottlenecks = [
            n for n in nodes
            if n["is_spof"] or n["betweenness_centrality"] > 0.05 or n["fragility_index"] >= 45.0
        ]

        bottlenecks.sort(
            key=lambda x: (x["is_spof"], x["fragility_index"], x["betweenness_centrality"]),
            reverse=True
        )
        return bottlenecks

    def get_subgraph(self, node_id: str) -> Dict[str, Any]:
        """
        Extracts 2-hop upstream and downstream dependency cascade for an inspected node.
        """
        graph = self.build_network_graph()
        if node_id not in graph.nodes:
            raise NotFoundError(f"Network node '{node_id}' not found.")

        upstream = graph.get_upstream_nodes(node_id)
        downstream = graph.get_downstream_nodes(node_id)
        subgraph_node_ids = {node_id} | upstream | downstream

        sub_nodes = [graph.nodes[n_id] for n_id in subgraph_node_ids]
        sub_edges = [
            edge_data for (src, tgt), edge_data in graph.edges.items()
            if src in subgraph_node_ids and tgt in subgraph_node_ids
        ]

        return {
            "root_node_id": node_id,
            "upstream_count": len(upstream),
            "downstream_count": len(downstream),
            "nodes": sub_nodes,
            "edges": sub_edges
        }

    def simulate_node_outage(self, node_id: str) -> Dict[str, Any]:
        """
        Simulates total failure/outage of a specific node (Spec §29).
        Calculates severed supply paths, stranded SKUs, and immediate monetary exposure.
        """
        graph = self.build_network_graph()
        if node_id not in graph.nodes:
            raise NotFoundError(f"Node '{node_id}' does not exist in supply network.")

        target_node = graph.nodes[node_id]
        downstream_nodes = graph.get_downstream_nodes(node_id)

        # Identify all downstream SKUs
        downstream_skus = [d for d in downstream_nodes if graph.nodes[d]["node_type"] == "PRODUCT"]

        # Check which SKUs become completely stranded (0 alternate suppliers remaining)
        stranded_skus: List[Dict[str, Any]] = []
        partially_degraded_skus: List[Dict[str, Any]] = []
        total_revenue_exposure = 0.0

        for sku_id in downstream_skus:
            sku_node = graph.nodes[sku_id]
            all_suppliers = {
                s for s in graph.pred.get(sku_id, set())
                if graph.nodes[s]["node_type"] == "TIER_1_SUPPLIER"
            }

            # Check remaining suppliers if node_id is removed
            remaining_suppliers = set()
            for s in all_suppliers:
                # If the supplier itself is removed, or if all its tier-2 suppliers are cut off
                if s != node_id:
                    s_upstream = graph.get_upstream_nodes(s)
                    if node_id not in s_upstream:
                        remaining_suppliers.add(s)

            unit_price = sku_node.get("unit_price", 0.0)
            on_hand = sku_node.get("on_hand", 0)
            exposure = round(unit_price * max(on_hand, 20), 2)

            if len(remaining_suppliers) == 0:
                stranded_skus.append({
                    "node_id": sku_id,
                    "sku": sku_node.get("sku"),
                    "name": sku_node.get("product_name"),
                    "on_hand": on_hand,
                    "unit_price": unit_price,
                    "revenue_exposure_inr": exposure,
                    "status": "SEVERED_ZERO_SUPPLIERS"
                })
                total_revenue_exposure += exposure
            else:
                partially_degraded_skus.append({
                    "node_id": sku_id,
                    "sku": sku_node.get("sku"),
                    "name": sku_node.get("product_name"),
                    "remaining_suppliers_count": len(remaining_suppliers),
                    "status": "DEGRADED_SECONDARY_ACTIVE"
                })

        return {
            "failed_node": target_node,
            "impact_summary": {
                "total_downstream_nodes_impacted": len(downstream_nodes),
                "total_skus_impacted": len(downstream_skus),
                "severed_skus_count": len(stranded_skus),
                "degraded_skus_count": len(partially_degraded_skus),
                "total_revenue_exposure_inr": round(total_revenue_exposure, 2),
                "severity": "CRITICAL" if len(stranded_skus) > 0 else "MEDIUM"
            },
            "severed_skus": stranded_skus,
            "degraded_skus": partially_degraded_skus,
            "recommended_mitigation": (
                f"Immediately qualify a secondary alternative vendor for {target_node['label']}. "
                f"Pre-buffer {len(stranded_skus)} critical SKUs with a 45-day safety inventory stock."
                if len(stranded_skus) > 0 else
                f"Shift order allocation to remaining active secondary suppliers."
            )
        }
