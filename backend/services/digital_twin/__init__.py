from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import numpy as np


@dataclass
class ShockConfig:
    """
    Configuration parameters for a simulated supply chain disruption (Spec §22).
    """
    shock_type: str  # SUPPLIER_OUTAGE, DEMAND_SURGE, LEAD_TIME_INFLATION, CAPITAL_FREEZE, CORRELATED_FAILURE
    name: str
    description: str
    target_supplier_id: Optional[int] = None
    target_sku: Optional[str] = None
    target_category: Optional[str] = None
    start_day: int = 5
    duration_days: int = 30
    magnitude: float = 1.0  # e.g., 2.5 for 2.5x demand surge, 14 for 14-day delay
    budget_limit_inr: Optional[float] = None


@dataclass
class DailySimState:
    """Daily record of network state during discrete-event simulation."""
    day: int
    date_str: str
    total_on_hand: int
    total_in_transit: int
    stockout_count: int
    units_demanded: int
    units_fulfilled: int
    units_lost: int
    revenue_lost_inr: float
    capital_tied_up_inr: float
    sku_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)
