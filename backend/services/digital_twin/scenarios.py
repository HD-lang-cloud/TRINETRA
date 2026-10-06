from typing import Dict, List, Any
from services.digital_twin import ShockConfig


def get_canonical_shock_presets() -> List[Dict[str, Any]]:
    """
    Returns library of canonical pre-configured stress test scenarios (Spec §22).
    """
    return [
        {
            "id": "canonical_supplier_outage",
            "name": "Single Point of Failure (SPOF) Supplier Outage",
            "shock_type": "SUPPLIER_OUTAGE",
            "description": "Critical supplier completely halts manufacturing and shipments for 30 days.",
            "target_supplier_id": 5,  # Monopoly Specialty Alloys or primary vendor
            "start_day": 5,
            "duration_days": 30,
            "magnitude": 0.0,
            "severity": "CRITICAL"
        },
        {
            "id": "canonical_demand_surge",
            "name": "Viral Demand Shock (3.0x Surge)",
            "shock_type": "DEMAND_SURGE",
            "description": "Sudden 300% demand surge across automotive & industrial sensors for 20 days.",
            "target_category": "Sensors",
            "start_day": 7,
            "duration_days": 20,
            "magnitude": 3.0,
            "severity": "HIGH"
        },
        {
            "id": "canonical_lead_time_inflation",
            "name": "Global Geopolitical Port Delay (+14 Days)",
            "shock_type": "LEAD_TIME_INFLATION",
            "description": "Freight bottlenecks and customs delays inflate all supplier lead times by +14 days.",
            "start_day": 1,
            "duration_days": 45,
            "magnitude": 14.0,
            "severity": "HIGH"
        },
        {
            "id": "canonical_capital_freeze",
            "name": "Working Capital Liquidity Freeze (Budget Capped)",
            "shock_type": "CAPITAL_FREEZE",
            "description": "Working capital constrained; maximum open PO capital expenditure capped at ₹75,000.",
            "start_day": 10,
            "duration_days": 30,
            "budget_limit_inr": 75000.0,
            "magnitude": 1.0,
            "severity": "MEDIUM"
        },
        {
            "id": "canonical_correlated_failure",
            "name": "Correlated Cascading Failure (Outage + Demand Surge)",
            "shock_type": "CORRELATED_FAILURE",
            "description": "Simultaneous shutdown of semiconductor foundry accompanied by a 2.5x demand surge.",
            "target_supplier_id": 1,
            "target_category": "Semiconductors",
            "start_day": 5,
            "duration_days": 25,
            "magnitude": 2.5,
            "severity": "CRITICAL"
        }
    ]
