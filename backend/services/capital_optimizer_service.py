"""
TRINETRA — Capital Optimization & Working Capital Allocation Engine (Phase 9, Spec §31, §32, §33)
Calculates Working Capital Pareto/Lorenz distributions, turnover velocities,
multi-echelon buffer rebalancing, and dead stock reclamation playbooks.
"""

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any, Optional
import sys

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = BASE_DIR / "backend"
for p in [str(BASE_DIR), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from database import get_db_connection
from repositories.product_repository import ProductRepository
from services.dna_service import InventoryDNAService
from services.replenishment_service import ReplenishmentService
from utils.logger import app_logger


class CapitalOptimizerService:
    """
    Core engine managing working capital allocation, portfolio buffer rebalancing,
    inventory turnover velocity (ITR/DSI), and dead stock liquidation playbooks.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.product_repo = ProductRepository(db_path=db_path)
        self.dna_service = InventoryDNAService(db_path=db_path)
        self.replenish_service = ReplenishmentService(db_path=db_path)

    def get_pareto_and_velocity_analytics(self) -> Dict[str, Any]:
        """
        Computes portfolio Working Capital Pareto distribution, Inventory Turnover Ratio (ITR),
        Days Sales of Inventory (DSI), and Gini coefficient of capital concentration (Spec §31).
        """
        products = self.product_repo.find_all()
        active_products = [p for p in products if p.get("status") != "DISCONTINUED"]

        if not active_products:
            return {
                "summary": {},
                "pareto_curve": [],
                "quadrants": {},
                "sku_analytics": []
            }

        sku_data: List[Dict[str, Any]] = []
        total_working_capital = 0.0
        total_annual_cogs = 0.0

        for p in active_products:
            dna = self.dna_service.calculate_dna(p["id"])
            m = dna["metrics"]
            tags = {c["tag"] for c in dna["classifications"]}

            unit_price = float(p["price"])
            # Estimate unit cost if not stored directly
            unit_cost = round(unit_price * 0.70, 2)
            on_hand = int(p["quantity"])
            capital_tied = round(on_hand * unit_cost, 2)
            total_working_capital += capital_tied

            daily_demand = max(0.0, float(m.get("demand_velocity_daily", 0.0)))
            annual_units_demanded = daily_demand * 365.0
            annual_cogs = round(annual_units_demanded * unit_cost, 2)
            total_annual_cogs += annual_cogs

            # Turnover Ratio & Days Sales of Inventory (DSI)
            itr = round(annual_cogs / max(capital_tied, 1.0), 2)
            dsi = round(365.0 / max(itr, 0.05), 1)

            # Capital Productivity Quadrant Classification
            if "DEAD STOCK" in tags or (itr < 0.8 and on_hand > 50):
                quadrant = "CAPITAL_TRAP"
                quadrant_label = "Capital Trap (Stagnant / Dead Stock)"
            elif itr >= 6.0:
                quadrant = "HIGH_VELOCITY_STAR"
                quadrant_label = "Star Cash Generator (High Turnover)"
            elif itr >= 2.5:
                quadrant = "BALANCED_WORKHORSE"
                quadrant_label = "Balanced Workhorse (Consistent Sales)"
            else:
                quadrant = "SLOW_TURNING_BUFFER"
                quadrant_label = "Slow-Turning Buffer"

            sku_data.append({
                "product_id": p["id"],
                "sku": p["sku"],
                "name": p["name"],
                "category": p["category"],
                "on_hand": on_hand,
                "unit_price": unit_price,
                "unit_cost": unit_cost,
                "capital_tied_inr": capital_tied,
                "annual_cogs_inr": annual_cogs,
                "itr": itr,
                "dsi_days": min(dsi, 999.0),
                "daily_demand": round(daily_demand, 2),
                "quadrant": quadrant,
                "quadrant_label": quadrant_label
            })

        # Sort descending by Annualized COGS for Pareto ABC ranking
        sku_data.sort(key=lambda x: x["annual_cogs_inr"], reverse=True)

        # Build Pareto Lorenz Curve (Cumulative % Capital vs Cumulative % SKU count)
        pareto_curve: List[Dict[str, Any]] = []
        cum_cogs = 0.0
        cum_capital = 0.0
        total_skus = len(sku_data)

        for i, item in enumerate(sku_data):
            cum_cogs += item["annual_cogs_inr"]
            cum_capital += item["capital_tied_inr"]
            cogs_pct = round((cum_cogs / max(total_annual_cogs, 1.0)) * 100.0, 1)
            capital_pct = round((cum_capital / max(total_working_capital, 1.0)) * 100.0, 1)
            sku_pct = round(((i + 1) / total_skus) * 100.0, 1)

            # ABC Classification based on COGS Pareto
            if cogs_pct <= 70.0:
                abc = "A"
            elif cogs_pct <= 90.0:
                abc = "B"
            else:
                abc = "C"

            item["abc_classification"] = abc
            item["cum_capital_pct"] = capital_pct
            item["cum_sku_pct"] = sku_pct

            pareto_curve.append({
                "sku": item["sku"],
                "name": item["name"],
                "sku_percentile": sku_pct,
                "cumulative_cogs_pct": cogs_pct,
                "cumulative_capital_pct": capital_pct,
                "abc_class": abc
            })

        # Calculate Gini Coefficient of capital concentration
        gini_coefficient = self._compute_gini_coefficient([x["capital_tied_inr"] for x in sku_data])

        # Quadrant Aggregation
        quadrants_summary: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "capital_inr": 0.0})
        for item in sku_data:
            q = item["quadrant"]
            quadrants_summary[q]["count"] += 1
            quadrants_summary[q]["capital_inr"] += item["capital_tied_inr"]

        for q in quadrants_summary:
            quadrants_summary[q]["capital_inr"] = round(quadrants_summary[q]["capital_inr"], 2)

        portfolio_itr = round(total_annual_cogs / max(total_working_capital, 1.0), 2)
        portfolio_dsi = round(365.0 / max(portfolio_itr, 0.05), 1)

        return {
            "summary": {
                "total_working_capital_inr": round(total_working_capital, 2),
                "total_annual_cogs_inr": round(total_annual_cogs, 2),
                "portfolio_itr": portfolio_itr,
                "portfolio_dsi_days": portfolio_dsi,
                "capital_gini_coefficient": gini_coefficient,
                "total_active_skus": total_skus
            },
            "quadrants": dict(quadrants_summary),
            "pareto_curve": pareto_curve,
            "sku_analytics": sku_data
        }

    def _compute_gini_coefficient(self, values: List[float]) -> float:
        """Computes standardized Gini coefficient for capital distribution (0.0 = uniform, 1.0 = absolute concentration)."""
        if not values or all(v == 0 for v in values):
            return 0.0
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        cum_sum = 0.0
        for i, val in enumerate(sorted_vals):
            cum_sum += (2 * (i + 1) - n - 1) * val
        total_sum = sum(sorted_vals)
        gini = cum_sum / (n * total_sum) if total_sum > 0 else 0.0
        return round(max(0.0, min(1.0, gini)), 3)

    def rebalance_portfolio_buffers(
        self,
        budget_ceiling_inr: Optional[float] = None,
        service_level: float = 0.95
    ) -> Dict[str, Any]:
        """
        Calculates optimal multi-echelon inventory buffer reallocation (Spec §32).
        Quantifies liquid capital to release from overstocked SKUs vs. capital injections
        needed to elevate stockout-prone SKUs to 95% service level.
        """
        products = self.product_repo.find_all()
        active_products = [p for p in products if p.get("status") != "DISCONTINUED"]

        capital_releases: List[Dict[str, Any]] = []
        capital_injections: List[Dict[str, Any]] = []
        balanced_skus: List[Dict[str, Any]] = []

        total_released_capital = 0.0
        total_injected_capital_needed = 0.0

        for p in active_products:
            prod_id = p["id"]
            on_hand = int(p["quantity"])
            unit_price = float(p["price"])
            unit_cost = round(unit_price * 0.70, 2)

            # Calculate ROP, Safety Stock, and EOQ
            rop_data = self.replenish_service.calculate_rop(prod_id, service_level=service_level)
            ss = rop_data["safety_stock"]
            eoq_data = self.replenish_service.calculate_eoq(prod_id)
            eoq = eoq_data.get("optimized_order_quantity", 10)

            # Optimal target stock = Safety Stock + 0.5 * Cycle Stock (EOQ)
            optimal_target_units = int(ss + round(eoq / 2.0))
            delta_units = optimal_target_units - on_hand

            if delta_units < -5:
                # Overstocked: can release capital
                excess_units = abs(delta_units)
                released_val = round(excess_units * unit_cost, 2)
                total_released_capital += released_val
                capital_releases.append({
                    "product_id": prod_id,
                    "sku": p["sku"],
                    "name": p["name"],
                    "current_on_hand": on_hand,
                    "optimal_target": optimal_target_units,
                    "excess_units": excess_units,
                    "unit_cost": unit_cost,
                    "capital_released_inr": released_val,
                    "action": "FREEZE_PURCHASES_BLEED_BUFFER",
                    "action_label": f"Release {excess_units} units excess buffer"
                })

            elif delta_units > 5:
                # Understocked: needs capital injection
                deficit_units = delta_units
                injection_val = round(deficit_units * unit_cost, 2)
                total_injected_capital_needed += injection_val
                capital_injections.append({
                    "product_id": prod_id,
                    "sku": p["sku"],
                    "name": p["name"],
                    "current_on_hand": on_hand,
                    "optimal_target": optimal_target_units,
                    "deficit_units": deficit_units,
                    "unit_cost": unit_cost,
                    "capital_required_inr": injection_val,
                    "action": "EXPEDITE_REPLENISHMENT",
                    "action_label": f"Inject {deficit_units} units to prevent stockout"
                })

            else:
                balanced_skus.append({
                    "product_id": prod_id,
                    "sku": p["sku"],
                    "name": p["name"],
                    "current_on_hand": on_hand,
                    "optimal_target": optimal_target_units,
                    "status": "BALANCED"
                })

        # Net balance
        net_delta = round(total_injected_capital_needed - total_released_capital, 2)
        funds_available = round(total_released_capital + (budget_ceiling_inr or 0.0), 2)
        budget_sufficient = funds_available >= total_injected_capital_needed

        return {
            "summary": {
                "target_service_level_pct": round(service_level * 100.0, 1),
                "total_capital_released_inr": round(total_released_capital, 2),
                "total_capital_injected_inr": round(total_injected_capital_needed, 2),
                "net_capital_delta_inr": net_delta,
                "reallocated_internal_funds_inr": round(min(total_released_capital, total_injected_capital_needed), 2),
                "external_budget_required_inr": round(max(0.0, total_injected_capital_needed - total_released_capital), 2),
                "budget_ceiling_inr": budget_ceiling_inr,
                "is_budget_sufficient": budget_sufficient,
                "overstocked_skus_count": len(capital_releases),
                "understocked_skus_count": len(capital_injections),
                "balanced_skus_count": len(balanced_skus)
            },
            "capital_releases": capital_releases,
            "capital_injections": capital_injections
        }

    def get_dead_stock_reclamation_playbook(self, holding_cost_rate: float = 0.20) -> Dict[str, Any]:
        """
        Identifies obsolete and stagnant capital and evaluates 4 structured reclamation strategies (Spec §33):
        1. Discount Markdown
        2. Supplier Buyback / RMA Credit
        3. Strategic Bundling
        4. Scrap & Tax Shield Offset
        """
        products = self.product_repo.find_all()
        dead_skus: List[Dict[str, Any]] = []
        total_tied_up = 0.0
        total_holding_cost_avoided = 0.0
        total_recoverable_capital = 0.0

        for p in products:
            if p.get("status") == "DISCONTINUED":
                continue

            dna = self.dna_service.calculate_dna(p["id"])
            tags = {c["tag"] for c in dna["classifications"]}
            m = dna["metrics"]

            is_dead = "DEAD STOCK" in tags or (m.get("demand_velocity_daily", 0.0) == 0.0 and p["quantity"] > 0)
            if not is_dead:
                continue

            on_hand = int(p["quantity"])
            unit_price = float(p["price"])
            unit_cost = round(unit_price * 0.70, 2)
            tied_capital = round(on_hand * unit_cost, 2)
            total_tied_up += tied_capital

            # 12-month holding cost burden (typically 20-25% of inventory value)
            annual_holding_cost = round(tied_capital * holding_cost_rate, 2)
            total_holding_cost_avoided += annual_holding_cost

            # 4 Tailored Reclamation Strategies
            strategies = [
                {
                    "strategy": "DISCOUNT_MARKDOWN",
                    "title": "Flash Clearance Markdown (35% Off)",
                    "recovery_rate_pct": 65.0,
                    "estimated_recovery_inr": round(tied_capital * 0.65, 2),
                    "holding_cost_avoided_inr": annual_holding_cost,
                    "timeframe_days": 14,
                    "description": "Immediate clearance across retail channels at 35% discount."
                },
                {
                    "strategy": "SUPPLIER_BUYBACK",
                    "title": "Supplier Buyback / RMA Credit (75% Restock Credit)",
                    "recovery_rate_pct": 75.0,
                    "estimated_recovery_inr": round(tied_capital * 0.75, 2),
                    "holding_cost_avoided_inr": annual_holding_cost,
                    "timeframe_days": 30,
                    "description": "Return unsealed modules to primary foundry for credit toward active MCU orders."
                },
                {
                    "strategy": "COMPLEMENTARY_BUNDLE",
                    "title": "Strategic Cross-Selling Bundle (20% Bundle Discount)",
                    "recovery_rate_pct": 80.0,
                    "estimated_recovery_inr": round(tied_capital * 0.80, 2),
                    "holding_cost_avoided_inr": annual_holding_cost,
                    "timeframe_days": 45,
                    "description": "Pair obsolete module with high-velocity SKU-FAST-01 as a discounted subsystem pack."
                },
                {
                    "strategy": "SALVAGE_SCRAP",
                    "title": "Salvage Disposal & Tax Shield Offset",
                    "recovery_rate_pct": 25.0,
                    "estimated_recovery_inr": round(tied_capital * 0.25, 2),
                    "holding_cost_avoided_inr": annual_holding_cost,
                    "timeframe_days": 7,
                    "description": "Liquidate component metals for raw scrap value and claim corporate inventory write-off."
                }
            ]

            # Best recommended option: Buyback if high recovery, else markdown
            best_opt = strategies[1] if on_hand >= 50 else strategies[0]
            total_recoverable_capital += best_opt["estimated_recovery_inr"]

            dead_skus.append({
                "product_id": p["id"],
                "sku": p["sku"],
                "name": p["name"],
                "on_hand": on_hand,
                "unit_price": unit_price,
                "unit_cost": unit_cost,
                "tied_up_capital_inr": tied_capital,
                "annual_holding_cost_inr": annual_holding_cost,
                "days_without_sales": 90,
                "recommended_strategy": best_opt["strategy"],
                "recommended_strategy_title": best_opt["title"],
                "projected_recovery_inr": best_opt["estimated_recovery_inr"],
                "strategies": strategies
            })

        return {
            "summary": {
                "dead_stock_skus_count": len(dead_skus),
                "total_stagnant_capital_inr": round(total_tied_up, 2),
                "total_holding_cost_avoided_inr": round(total_holding_cost_avoided, 2),
                "total_projected_recoverable_capital_inr": round(total_recoverable_capital, 2),
                "holding_cost_rate_pct": round(holding_cost_rate * 100.0, 1)
            },
            "dead_skus": dead_skus
        }

    def evaluate_holding_cost_sensitivity(
        self,
        rates: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        Simulates financial liquidity sensitivity across holding cost rate variations (Spec §31, §33).
        Tests rates [15%, 20%, 25%, 30%] against current portfolio inventory and dead stock.
        """
        test_rates = rates or [0.15, 0.20, 0.25, 0.30]
        pareto = self.get_pareto_and_velocity_analytics()
        total_working_capital = pareto["summary"]["total_working_capital_inr"]
        dead_playbook = self.get_dead_stock_reclamation_playbook()
        dead_capital = dead_playbook["summary"]["total_stagnant_capital_inr"]

        sensitivity_curve: List[Dict[str, Any]] = []
        for r in test_rates:
            annual_holding_cost = round(total_working_capital * r, 2)
            dead_holding_cost = round(dead_capital * r, 2)
            sensitivity_curve.append({
                "holding_cost_rate_pct": round(r * 100.0, 1),
                "total_annual_holding_cost_inr": annual_holding_cost,
                "dead_stock_carrying_penalty_inr": dead_holding_cost,
                "monthly_cash_drag_inr": round(annual_holding_cost / 12.0, 2)
            })

        return {
            "total_working_capital_inr": total_working_capital,
            "dead_stock_capital_inr": dead_capital,
            "sensitivity_curve": sensitivity_curve
        }
