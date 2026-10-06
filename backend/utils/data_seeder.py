import math
import random
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import db_transaction, get_db_connection
from utils.logger import app_logger


def seed_demo_dataset(db_path: Optional[str] = None, seed: int = 42) -> dict:
    """
    Generates a reproducible seeded dataset embodying 7 distinct supply chain stories:
    1. Fast-Moving Healthy: High velocity, low volatility, reliable supplier.
    2. Demand Spike: Sudden recent surge, elevated stockout exposure.
    3. Supplier Concentration (SPOF): High dependence on single unreliable vendor.
    4. Dead Stock: Stagnant inventory, zero recent sales, tied-up working capital.
    5. Capital Heavy: High unit cost, large revenue impact.
    6. Seasonal SKU: Clear cyclical demand oscillation.
    7. Sparse / Insufficient Data: Brand new SKU with only 5 days of history (tests sufficiency gates).

    All synthetic records are explicitly tagged with is_synthetic = 1 (Spec §43).
    """
    random.seed(seed)
    app_logger.info(f"Generating reproducible demo dataset (seed={seed})")

    today = datetime.now(timezone.utc).date()

    with db_transaction(db_path) as conn:
        # Clear existing synthetic data cleanly
        conn.execute("DELETE FROM demand_history WHERE is_synthetic = 1")
        conn.execute("DELETE FROM anomalies")
        conn.execute("DELETE FROM risk_scores")
        conn.execute("DELETE FROM supplier_products")

        # 0. Seed Standard Users & Operators
        users = [
            (1, "lead_operator", "operator@trinetra.internal", "mock_hash_1", "Inventory Manager"),
            (2, "system_admin", "admin@trinetra.internal", "mock_hash_2", "Admin"),
            (3, "risk_analyst", "analyst@trinetra.internal", "mock_hash_3", "Analyst")
        ]
        for uid, uname, email, pw, role in users:
            conn.execute(
                """
                INSERT INTO users (id, username, email, password_hash, role)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET username=excluded.username, role=excluded.role
                """,
                (uid, uname, email, pw, role)
            )

        # 1. Seed Categories
        categories = [
            ("Semiconductors", "Active processors, microcontrollers, and SoC modules"),
            ("Sensors", "Industrial pressure, temperature, and optical telemetry sensors"),
            ("Power Systems", "Battery management, switching converters, and regulators"),
            ("Mechanical", "Actuators, valves, gears, and structural enclosures"),
            ("Passive Components", "Precision resistors, capacitors, and inductors")
        ]
        cat_ids = {}
        for name, desc in categories:
            cursor = conn.execute(
                "INSERT INTO categories (name, description) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET description=excluded.description",
                (name, desc)
            )
            row = conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
            cat_ids[name] = row["id"]

        # 2. Seed Locations
        locations = [
            ("WH-MAIN", "Central Fulfilment Hub", "Zone 1 Logistics Park, Sector 4", "WAREHOUSE"),
            ("WH-NORTH", "Regional North Hub", "Industrial Corridor 12, Terminal B", "WAREHOUSE"),
            ("STORE-01", "Metropolitan Retail Depot", "Commercial Arcade, Plaza Level", "STORE")
        ]
        loc_ids = {}
        for code, name, addr, ltype in locations:
            conn.execute(
                """
                INSERT INTO locations (code, name, address, location_type)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET name=excluded.name
                """,
                (code, name, addr, ltype)
            )
            row = conn.execute("SELECT id FROM locations WHERE code = ?", (code,)).fetchone()
            loc_ids[code] = row["id"]

        main_loc_id = loc_ids["WH-MAIN"]

        # 3. Seed Suppliers (Tier-1 Direct & Tier-2 Raw Material Foundries, Spec §28)
        suppliers = [
            # Tier-1 Direct Component Suppliers
            ("Apex Semiconductor Corp", "orders@apexsemi.com", 7, 1.2, 0.96, "ACTIVE", 1),
            ("Vertex Precision Foundry", "supply@vertexfoundry.com", 14, 3.5, 0.78, "WARNING", 1),
            ("Kyoto Sensors Inc", "dispatch@kyotosensors.jp", 10, 1.0, 0.94, "ACTIVE", 1),
            ("Reliant Power Logistics", "procure@reliantpower.com", 5, 0.8, 0.98, "ACTIVE", 1),
            ("Monopoly Specialty Alloys", "sales@monopolyalloys.com", 21, 6.0, 0.65, "WARNING", 1),
            # Tier-2 Upstream Raw Material & Substrate Providers
            ("Global Silicon Crystals GmbH", "wafers@siliconcrystals.de", 28, 4.0, 0.92, "ACTIVE", 2),
            ("Nippon Piezoelectric Raw Minerals", "minerals@nipponpiezo.jp", 35, 5.0, 0.88, "ACTIVE", 2),
            ("Ural Rare Earth Mining Consortium", "export@uralrareearth.ru", 45, 8.0, 0.60, "WARNING", 2)
        ]
        supp_ids = {}
        for name, email, lead, var, rel, status, tier in suppliers:
            conn.execute(
                """
                INSERT INTO suppliers (name, contact_email, lead_time_days, lead_time_variance, reliability_score, status, tier)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    lead_time_days=excluded.lead_time_days,
                    lead_time_variance=excluded.lead_time_variance,
                    reliability_score=excluded.reliability_score,
                    status=excluded.status,
                    tier=excluded.tier
                """,
                (name, email, lead, var, rel, status, tier)
            )
            row = conn.execute("SELECT id FROM suppliers WHERE name = ?", (name,)).fetchone()
            supp_ids[name] = row["id"]

        # Seed Tier-2 to Tier-1 Supply Dependencies (Spec §28)
        tier2_deps = [
            ("Global Silicon Crystals GmbH", "Apex Semiconductor Corp", "300mm Monocrystalline Silicon Wafers", 28, "HIGH"),
            ("Global Silicon Crystals GmbH", "Vertex Precision Foundry", "Raw Semiconductor Grade Polysilicon", 21, "MEDIUM"),
            ("Nippon Piezoelectric Raw Minerals", "Kyoto Sensors Inc", "Synthetic Quartz & PZT Ceramic Ingots", 35, "HIGH"),
            ("Ural Rare Earth Mining Consortium", "Monopoly Specialty Alloys", "Heavy Rare Earth Concentrate (Dy/Tb)", 45, "CRITICAL")
        ]
        for t2_name, t1_name, mat, lead, crit in tier2_deps:
            t2_id = supp_ids[t2_name]
            t1_id = supp_ids[t1_name]
            conn.execute(
                """
                INSERT INTO supplier_tier_dependencies (tier2_supplier_id, tier1_supplier_id, material_name, lead_time_days, criticality)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tier2_supplier_id, tier1_supplier_id) DO UPDATE SET
                    material_name=excluded.material_name,
                    lead_time_days=excluded.lead_time_days,
                    criticality=excluded.criticality
                """,
                (t2_id, t1_id, mat, lead, crit)
            )

        # 4. Seed 7 Core Product Archetypes
        product_archetypes = [
            {
                "sku": "SKU-FAST-01",
                "name": "STM32 High-Velocity Microcontroller",
                "category": "Semiconductors",
                "quantity": 180,
                "price": 650.0,
                "reorder_threshold": 60,
                "target_stock_level": 250,
                "description": "Fast-moving 32-bit automotive-grade MCU with stable demand.",
                "story": "fast_moving",
                "primary_supplier": "Apex Semiconductor Corp",
                "secondary_supplier": "Vertex Precision Foundry"
            },
            {
                "sku": "SKU-SPIKE-02",
                "name": "Infrared Thermal Telemetry Sensor",
                "category": "Sensors",
                "quantity": 24,
                "price": 1850.0,
                "reorder_threshold": 35,
                "target_stock_level": 120,
                "description": "High stockout risk due to an unexpected 3x demand surge in the last 10 days.",
                "story": "demand_spike",
                "primary_supplier": "Kyoto Sensors Inc",
                "secondary_supplier": None
            },
            {
                "sku": "SKU-SPOF-03",
                "name": "Monolithic FPGA Accelerator Board",
                "category": "Semiconductors",
                "quantity": 15,
                "price": 18500.0,
                "reorder_threshold": 12,
                "target_stock_level": 40,
                "description": "Critical single point of failure: 100% dependent on an unreliable vendor with 21-day lead time.",
                "story": "spof",
                "primary_supplier": "Monopoly Specialty Alloys",
                "secondary_supplier": None
            },
            {
                "sku": "SKU-DEAD-04",
                "name": "Legacy Electromechanical Relay Module",
                "category": "Passive Components",
                "quantity": 220,
                "price": 320.0,
                "reorder_threshold": 20,
                "target_stock_level": 50,
                "description": "Dead stock: Zero consumption in over 60 days. Tying up ₹70,400 in idle working capital.",
                "story": "dead_stock",
                "primary_supplier": "Reliant Power Logistics",
                "secondary_supplier": None
            },
            {
                "sku": "SKU-CAP-05",
                "name": "Precision Servo Robotic Actuator",
                "category": "Mechanical",
                "quantity": 8,
                "price": 145000.0,
                "reorder_threshold": 4,
                "target_stock_level": 15,
                "description": "Capital heavy: Represents high capital exposure (₹1.16M). Requires tight inventory control.",
                "story": "capital_heavy",
                "primary_supplier": "Vertex Precision Foundry",
                "secondary_supplier": "Apex Semiconductor Corp"
            },
            {
                "sku": "SKU-SEAS-06",
                "name": "Sub-Zero Cryogenic Cooling Valve",
                "category": "Mechanical",
                "quantity": 42,
                "price": 4200.0,
                "reorder_threshold": 20,
                "target_stock_level": 80,
                "description": "Seasonal demand pattern with 30-day cyclical crests and troughs.",
                "story": "seasonal",
                "primary_supplier": "Reliant Power Logistics",
                "secondary_supplier": "Kyoto Sensors Inc"
            },
            {
                "sku": "SKU-NEW-07",
                "name": "Quantum Magnetometer Prototype",
                "category": "Sensors",
                "quantity": 10,
                "price": 48000.0,
                "reorder_threshold": 5,
                "target_stock_level": 25,
                "description": "New product introduction with only 5 days of history. Used to test data sufficiency gates.",
                "story": "sparse_data",
                "primary_supplier": "Kyoto Sensors Inc",
                "secondary_supplier": None
            }
        ]

        seeded_products = []

        for arch in product_archetypes:
            cat_id = cat_ids[arch["category"]]
            existing = conn.execute("SELECT id FROM products WHERE sku = ?", (arch["sku"],)).fetchone()
            
            if existing:
                prod_id = existing["id"]
                conn.execute(
                    """
                    UPDATE products SET 
                        name = ?, category = ?, category_id = ?, quantity = ?, price = ?,
                        reorder_threshold = ?, target_stock_level = ?, description = ?, status = 'ACTIVE'
                    WHERE id = ?
                    """,
                    (
                        arch["name"], arch["category"], cat_id, arch["quantity"], arch["price"],
                        arch["reorder_threshold"], arch["target_stock_level"], arch["description"], prod_id
                    )
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO products 
                    (sku, name, category, category_id, quantity, price, reorder_threshold, target_stock_level, description, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
                    """,
                    (
                        arch["sku"], arch["name"], arch["category"], cat_id,
                        arch["quantity"], arch["price"], arch["reorder_threshold"],
                        arch["target_stock_level"], arch["description"]
                    )
                )
                prod_id = cursor.lastrowid

            prod = conn.execute("SELECT * FROM products WHERE id = ?", (prod_id,)).fetchone()
            seeded_products.append(prod)

            # Map inventory to main warehouse
            conn.execute(
                """
                INSERT INTO inventory (product_id, location_id, quantity, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(product_id, location_id) DO UPDATE SET quantity=excluded.quantity
                """,
                (prod_id, main_loc_id, arch["quantity"])
            )

            # Link primary supplier
            p_supp_id = supp_ids[arch["primary_supplier"]]
            conn.execute(
                """
                INSERT INTO supplier_products (supplier_id, product_id, unit_cost, moq, supplier_lead_time_days, is_primary)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(supplier_id, product_id) DO UPDATE SET is_primary=1
                """,
                (p_supp_id, prod_id, arch["price"] * 0.75, 5, 7)
            )

            # Link secondary supplier if available
            if arch["secondary_supplier"]:
                s_supp_id = supp_ids[arch["secondary_supplier"]]
                conn.execute(
                    """
                    INSERT INTO supplier_products (supplier_id, product_id, unit_cost, moq, supplier_lead_time_days, is_primary)
                    VALUES (?, ?, ?, ?, ?, 0)
                    ON CONFLICT(supplier_id, product_id) DO UPDATE SET is_primary=0
                    """,
                    (s_supp_id, prod_id, arch["price"] * 0.85, 10, 12)
                )

            # 5. Generate 90 Days of Historical Daily Demand according to story
            story = arch["story"]
            history_days = 5 if story == "sparse_data" else 90

            for d in range(history_days, 0, -1):
                hist_date = (today - timedelta(days=d)).isoformat()

                if story == "fast_moving":
                    # Steady baseline 15-20 units/day + weekend dip
                    day_of_week = (today - timedelta(days=d)).weekday()
                    base = 12 if day_of_week >= 5 else 18
                    noise = random.randint(-3, 3)
                    qty_demanded = max(5, base + noise)

                elif story == "demand_spike":
                    # Stable (4 units/day) until last 10 days, where it triples to 14-18 units/day
                    if d <= 10:
                        qty_demanded = random.randint(14, 20)
                    else:
                        qty_demanded = random.randint(3, 6)

                elif story == "spof":
                    # Moderate demand (2-4 units/day) with occasional supply delays
                    qty_demanded = random.randint(2, 4)

                elif story == "dead_stock":
                    # Activity 60-90 days ago, exactly 0 demand in the last 60 days
                    if d > 60:
                        qty_demanded = random.randint(1, 3)
                    else:
                        qty_demanded = 0

                elif story == "capital_heavy":
                    # Low discrete demand (0 to 1 unit every 3 days)
                    qty_demanded = 1 if (d % 3 == 0 and random.random() > 0.3) else 0

                elif story == "seasonal":
                    # Sinusoidal cycle with 30-day period: base + amplitude * sin(2*pi*d/30)
                    cycle = math.sin((2 * math.pi * (90 - d)) / 30.0)
                    qty_demanded = max(1, int(10 + 7 * cycle + random.randint(-2, 2)))

                elif story == "sparse_data":
                    qty_demanded = random.randint(1, 3)

                else:
                    qty_demanded = random.randint(2, 8)

                conn.execute(
                    """
                    INSERT INTO demand_history (product_id, date, quantity_demanded, is_synthetic)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(product_id, date) DO UPDATE SET quantity_demanded=excluded.quantity_demanded
                    """,
                    (prod_id, hist_date, qty_demanded)
                )

            # Record sample opening stock movement in audit ledger
            conn.execute(
                """
                INSERT INTO stock_movements 
                (product_id, location_id, movement_type, quantity_change, balance_after, reference_id, reason)
                VALUES (?, ?, 'PURCHASE', ?, ?, 'SEED-INITIAL-2026', 'Automated seed baseline initialization')
                """,
                (prod_id, main_loc_id, arch["quantity"], arch["quantity"])
            )

    app_logger.info(f"Seeded {len(seeded_products)} products with 90-day demand histories successfully.")
    return {
        "status": "success",
        "products_seeded": len(seeded_products),
        "seed_value": seed
    }


if __name__ == "__main__":
    seed_demo_dataset()
