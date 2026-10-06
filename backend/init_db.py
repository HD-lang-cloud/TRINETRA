from pathlib import Path
from typing import Optional
from database import get_db_connection
from utils.logger import app_logger


def migrate_existing_tables(conn) -> None:
    """Safely upgrades any legacy tables to the latest TRINETRA schema without data loss."""
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
    if cursor.fetchone():
        # Inspect columns in products table
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(products)").fetchall()]
        
        if "sku" not in columns:
            app_logger.info("Migrating products table: adding 'sku' column")
            conn.execute("ALTER TABLE products ADD COLUMN sku TEXT")
            conn.execute("UPDATE products SET sku = 'SKU-' || printf('%04d', id) WHERE sku IS NULL")
            
        if "target_stock_level" not in columns:
            app_logger.info("Migrating products table: adding 'target_stock_level' column")
            conn.execute("ALTER TABLE products ADD COLUMN target_stock_level INTEGER NOT NULL DEFAULT 50")
            
        if "description" not in columns:
            app_logger.info("Migrating products table: adding 'description' column")
            conn.execute("ALTER TABLE products ADD COLUMN description TEXT")
            
        if "status" not in columns:
            app_logger.info("Migrating products table: adding 'status' column")
            conn.execute("ALTER TABLE products ADD COLUMN status TEXT NOT NULL DEFAULT 'ACTIVE'")
            
        if "category_id" not in columns:
            app_logger.info("Migrating products table: adding 'category_id' column")
            conn.execute("ALTER TABLE products ADD COLUMN category_id INTEGER")
            
        conn.commit()

    cursor_supp = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='suppliers'")
    if cursor_supp.fetchone():
        supp_cols = [row["name"] for row in conn.execute("PRAGMA table_info(suppliers)").fetchall()]
        if "tier" not in supp_cols:
            app_logger.info("Migrating suppliers table: adding 'tier' column")
            conn.execute("ALTER TABLE suppliers ADD COLUMN tier INTEGER NOT NULL DEFAULT 1")
            conn.commit()


SCHEMA_SQL = """
-- 1. Users & RBAC
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'Viewer' CHECK(role IN ('Admin', 'Inventory Manager', 'Analyst', 'Viewer')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Categories
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Suppliers
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    contact_email TEXT,
    phone TEXT,
    lead_time_days INTEGER NOT NULL DEFAULT 7 CHECK(lead_time_days >= 0),
    lead_time_variance REAL NOT NULL DEFAULT 1.0 CHECK(lead_time_variance >= 0),
    reliability_score REAL NOT NULL DEFAULT 1.0 CHECK(reliability_score >= 0.0 AND reliability_score <= 1.0),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'WARNING', 'SUSPENDED')),
    tier INTEGER NOT NULL DEFAULT 1 CHECK(tier IN (1, 2)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Locations (Warehouses / Distribution Centers)
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    address TEXT,
    location_type TEXT NOT NULL DEFAULT 'WAREHOUSE' CHECK(location_type IN ('WAREHOUSE', 'STORE', 'IN_TRANSIT')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. Products Catalogue
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    category_id INTEGER,
    quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
    price REAL NOT NULL CHECK(price >= 0),
    reorder_threshold INTEGER NOT NULL DEFAULT 10 CHECK(reorder_threshold >= 0),
    target_stock_level INTEGER NOT NULL DEFAULT 50 CHECK(target_stock_level >= 0),
    description TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'DISCONTINUED', 'SEASONAL')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE SET NULL
);

-- 6. Supplier Products (Multi-supplier mapping)
CREATE TABLE IF NOT EXISTS supplier_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    unit_cost REAL NOT NULL CHECK(unit_cost >= 0),
    moq INTEGER NOT NULL DEFAULT 1 CHECK(moq >= 1),
    supplier_lead_time_days INTEGER NOT NULL DEFAULT 7 CHECK(supplier_lead_time_days >= 0),
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (supplier_id) REFERENCES suppliers (id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE,
    UNIQUE (supplier_id, product_id)
);

-- 6b. Multi-Tier Supplier Dependencies (Spec §28)
CREATE TABLE IF NOT EXISTS supplier_tier_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tier2_supplier_id INTEGER NOT NULL,
    tier1_supplier_id INTEGER NOT NULL,
    material_name TEXT NOT NULL,
    lead_time_days INTEGER NOT NULL DEFAULT 14 CHECK(lead_time_days >= 0),
    criticality TEXT NOT NULL DEFAULT 'HIGH' CHECK(criticality IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tier2_supplier_id) REFERENCES suppliers(id) ON DELETE CASCADE,
    FOREIGN KEY (tier1_supplier_id) REFERENCES suppliers(id) ON DELETE CASCADE,
    UNIQUE (tier2_supplier_id, tier1_supplier_id)
);

-- 7. Inventory (Location Stock Levels)
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    location_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
    reserved_quantity INTEGER NOT NULL DEFAULT 0 CHECK(reserved_quantity >= 0),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE,
    FOREIGN KEY (location_id) REFERENCES locations (id) ON DELETE CASCADE,
    UNIQUE (product_id, location_id)
);

-- 8. Immutable Stock Movement Ledger
CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    location_id INTEGER,
    movement_type TEXT NOT NULL CHECK(
        movement_type IN ('PURCHASE', 'SALE', 'ADJUSTMENT', 'TRANSFER', 'RETURN', 'DAMAGE', 'EXPIRY', 'EMERGENCY')
    ),
    quantity_change INTEGER NOT NULL,
    balance_after INTEGER NOT NULL CHECK(balance_after >= 0),
    reference_id TEXT,
    reason TEXT NOT NULL,
    user_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE,
    FOREIGN KEY (location_id) REFERENCES locations (id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
);

-- 9. Historical Demand Data (For Time-Series Forecasting)
CREATE TABLE IF NOT EXISTS demand_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    quantity_demanded INTEGER NOT NULL CHECK(quantity_demanded >= 0),
    is_synthetic INTEGER NOT NULL DEFAULT 0 CHECK(is_synthetic IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE,
    UNIQUE (product_id, date)
);

-- 10. Forecast Outputs & Benchmarks
CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    forecast_date TEXT NOT NULL,
    predicted_demand REAL NOT NULL CHECK(predicted_demand >= 0),
    confidence_lower REAL DEFAULT 0,
    confidence_upper REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS forecast_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    training_window TEXT,
    mae REAL,
    rmse REAL,
    smape REAL,
    bias REAL,
    selected INTEGER NOT NULL DEFAULT 0 CHECK(selected IN (0, 1)),
    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
);

-- 11. Risk Scores & Anomalies
CREATE TABLE IF NOT EXISTS risk_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    stockout_risk_pct REAL NOT NULL DEFAULT 0.0,
    overstock_risk_pct REAL NOT NULL DEFAULT 0.0,
    supplier_risk_pct REAL NOT NULL DEFAULT 0.0,
    capital_at_risk REAL NOT NULL DEFAULT 0.0,
    composite_rating TEXT NOT NULL DEFAULT 'LOW' CHECK(composite_rating IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    evidence_json TEXT,
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    anomaly_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    description TEXT NOT NULL,
    evidence_json TEXT,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 12. Digital Twin Scenarios & Results
CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    baseline_snapshot_json TEXT NOT NULL,
    shock_parameters_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'COMPLETED' CHECK(status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scenario_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id INTEGER NOT NULL,
    projected_stockouts INTEGER NOT NULL DEFAULT 0,
    revenue_exposure REAL NOT NULL DEFAULT 0.0,
    resilience_score_delta REAL NOT NULL DEFAULT 0.0,
    critical_skus_json TEXT,
    recovery_options_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (scenario_id) REFERENCES scenarios (id) ON DELETE CASCADE
);

-- 13. Decision Ledger & Human-in-the-Loop Tracking
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    recommendation_type TEXT NOT NULL,
    what TEXT NOT NULL,
    why TEXT NOT NULL,
    evidence_json TEXT,
    confidence_pct REAL NOT NULL,
    alternative_options_json TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED', 'MODIFIED')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE
);

-- Purchase Orders & Replenishment Execution (Spec §20, §35)
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number TEXT UNIQUE NOT NULL,
    supplier_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'SENT', 'RECEIVED', 'CANCELLED')),
    total_amount REAL NOT NULL DEFAULT 0.0 CHECK(total_amount >= 0),
    currency TEXT NOT NULL DEFAULT 'INR',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP,
    FOREIGN KEY (supplier_id) REFERENCES suppliers (id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS purchase_order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_cost REAL NOT NULL CHECK(unit_cost >= 0),
    subtotal REAL NOT NULL CHECK(subtotal >= 0),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (purchase_order_id) REFERENCES purchase_orders (id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id INTEGER NOT NULL,
    user_id INTEGER,
    decision_type TEXT NOT NULL CHECK(decision_type IN ('APPROVED', 'REJECTED', 'MODIFIED')),
    override_reason TEXT,
    execution_status TEXT NOT NULL DEFAULT 'EXECUTED' CHECK(execution_status IN ('PENDING', 'EXECUTED', 'FAILED')),
    decided_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (recommendation_id) REFERENCES recommendations (id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS decision_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL,
    outcome_type TEXT NOT NULL,
    observed_result TEXT NOT NULL,
    stockout_avoided INTEGER DEFAULT 1,
    savings_amount REAL DEFAULT 0.0,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (decision_id) REFERENCES decisions (id) ON DELETE CASCADE
);

-- 14. Auditability & System Events
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    before_state_json TEXT,
    after_state_json TEXT,
    reason TEXT,
    ip_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'INFO' CHECK(severity IN ('INFO', 'WARNING', 'ERROR')),
    message TEXT NOT NULL,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    version TEXT NOT NULL,
    parameters_json TEXT,
    training_start_date TEXT,
    training_end_date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 15. Governed Autonomous Agent Operations & Guardrail Auditing
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE NOT NULL,
    agent_name TEXT NOT NULL,
    agent_goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'RUNNING' CHECK(status IN ('RUNNING', 'COMPLETED', 'BLOCKED', 'FAILED')),
    governance_mode TEXT NOT NULL DEFAULT 'HUMAN_APPROVAL_REQUIRED' CHECK(governance_mode IN ('AUTONOMOUS_APPROVED', 'HUMAN_APPROVAL_REQUIRED', 'CIRCUIT_BREAKER_BLOCKED')),
    confidence_score REAL NOT NULL DEFAULT 0.0,
    rationale TEXT NOT NULL,
    actions_proposed_json TEXT,
    guardrail_decision TEXT NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_tool_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_run_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input_parameters_json TEXT,
    output_result_json TEXT,
    execution_status TEXT NOT NULL DEFAULT 'SUCCESS' CHECK(execution_status IN ('SUCCESS', 'FAILURE', 'GUARDRAIL_BLOCKED')),
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_guardrail_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_run_id TEXT NOT NULL,
    policy_name TEXT NOT NULL,
    rule_evaluated TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK(verdict IN ('PASS', 'VIOLATION_BLOCKED', 'HUMAN_OVERRIDE_ESCALATION')),
    remediation_required TEXT,
    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);

-- Indexes for Query Performance & Analytics
CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_inventory_product_loc ON inventory(product_id, location_id);
CREATE INDEX IF NOT EXISTS idx_movements_product_time ON stock_movements(product_id, created_at);
CREATE INDEX IF NOT EXISTS idx_demand_product_date ON demand_history(product_id, date);
CREATE INDEX IF NOT EXISTS idx_forecasts_product_date ON forecasts(product_id, forecast_date);
CREATE INDEX IF NOT EXISTS idx_risk_scores_product ON risk_scores(product_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_runs_run_id ON agent_runs(run_id);
"""


def initialize_database(db_path: Optional[str | Path] = None) -> bool:
    """
    Initializes the SQLite database with full TRINETRA schema.
    Applies migrations to preserve existing data, enforces foreign keys, and builds indexes.
    """
    app_logger.info(f"Initializing TRINETRA database schema at: {db_path or 'default'}")
    conn = get_db_connection(db_path)
    try:
        # Step 1: Migrate existing tables safely
        migrate_existing_tables(conn)
        
        # Step 2: Execute full schema
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        app_logger.info("TRINETRA database schema initialized successfully.")
        return True
    except Exception as e:
        app_logger.error(f"Failed to initialize TRINETRA database schema: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    initialize_database()
