# TRINETRA (त्रिनेत्र)
> **SEE. FORESEE. PREPARE.**  
> *Autonomous, Audit-Grade, Self-Healing Inventory Resilience & Decision Intelligence Operating System*

---

## 👁️ Overview

**TRINETRA** is an enterprise-grade inventory intelligence and resilience operating system built to protect mission-critical supply networks from disruptions, stockouts, capital lockup, and data drift. It bridges real-time inventory management with stochastic digital twin simulations, time-series forecasting, multi-echelon buffer allocation, and autonomous self-healing database guardrails.

---

## 🌟 Key Architecture & Capabilities

### 1. 🛡️ Operational Intelligence & DNA Matrix
- **Inventory DNA**: Automatic categorization into 7 behavioral archetypes (Fast-Moving, Volatile Lumpy, Seasonal, Capital Heavy, Dead Stock, etc.).
- **8D Risk Scoring**: Composite multi-dimensional risk scores (0–100) quantifying stockout vulnerability, overstock risk, vendor concentration, and capital at risk.
- **Statistical Anomaly Detection**: Real-time rolling Z-Score ($Z \ge 2.5$) and Interquartile Range (IQR) outlier detection on continuous demand streams.

### 2. 🔮 Demand Forecasting Engine & Benchmark Suite
- **Multi-Model Tournament**: Automatically evaluates Baseline (Moving Average, Exponential Smoothing), Machine Learning (Gradient Boosted Regressor), and Deep Learning (Gated Recurrent Unit - GRU) architectures.
- **Data Sufficiency Gatekeepers**: Temporal train/test splitting with validation safeguards to prevent statistical data leakage.
- **Automated Champion Selection**: Selects champion models per SKU based on MAE, RMSE, and sMAPE validation performance.

### 3. ⚙️ Replenishment Policy & Order Optimization
- **Dynamic Safety Stock & ROP**: Real-time Reorder Point ($ROP = d_L + SS$) dynamically adjusted for lead-time variance.
- **Economic Order Quantity (EOQ)**: Constrained EOQ optimization respecting supplier Minimum Order Quantities (MOQ).
- **Consolidated Purchase Orders**: Intelligent multi-SKU purchase order generation to minimize freight overhead.

### 4. 🌀 Digital Twin Simulation & Shock Testing (Resilience Lab)
- **Monte Carlo Stochastic Engine**: Simulates inventory trajectories over 30 to 180 day horizons without mutating production databases.
- **Stress-Test Scenarios**:
  - *Supplier Outages*: Extended vendor lead time disruptions.
  - *Demand Surges*: Black Friday / surge events ($+100\%$ to $+300\%$).
  - *Cascading Shocks*: Correlated compound failures across interdependent multi-tier supply networks.

### 5. 🕸️ Supply Network Graph & Multitier Topology Engine
- **Hierarchical Graph Analysis**: Pure Python directed graph engine modeling Tier-2 foundries, Tier-1 suppliers, distribution centers, and end SKUs.
- **Brandes' Centrality & Bottleneck Detection**: Calculates Betweenness Centrality, Degree Centrality, and identifies Single Points of Failure (SPOFs).
- **Outage Blast Radius Simulation**: Downstream dependency traversal to calculate total revenue at risk during node disruptions.

### 6. ⚖️ Working Capital Optimization & Buffer Rebalancing
- **Pareto Velocity Matrix**: Computes Inventory Turnover Ratio (ITR), Days Sales of Inventory (DSI), and the Gini coefficient of capital concentration.
- **Multi-Echelon Buffer Rebalancing**: Reallocates capital by harvesting overstocked safety buffers to finance stockout-vulnerable SKUs.
- **Dead Stock Reclamation Playbook**: Evaluates 4 liquidation pathways (Promotional Markdown, Supplier Buyback, Strategic Bundle, Scrap Tax Shield).

### 7. ⚖️ Human-in-the-Loop Decision Ledger & Action Studio
- **Dual-Pane Action Studio**: Streamlines replenishment approval workflows with confidence scores and explainable rationale.
- **Operator Decision Overrides**: Requires mandatory operational justifications for overrides with an immutable audit trail.
- **Closed-Loop Outcome Verification**: Tracks real-world outcomes (stockouts avoided, capital saved) to evaluate decision efficacy.

### 8. 🩺 Production Observability & Autonomous Self-Healing Guardrails
- **Automated Self-Healing Reconciler**: Audits and auto-repairs 4 core database invariants (ledger synchronization, negative stock prevention, PO subtotal integrity, location inventory consistency).
- **Statistical Demand Drift Detection**: Population Stability Index (PSI) and Wasserstein Z-distance tracking between baseline and recent demand horizons.
- **Autonomous Circuit Breakers**: Automatically transitions to `SAFE_MODE` if anomaly densities or crisis ratios exceed safety thresholds.

---

## 🚀 Quickstart

### Prerequisites
- Python 3.10+ (Tested on Python 3.13)
- Modern web browser (Chrome, Edge, Firefox, Safari)

### Installation & Setup

1. **Clone & Setup Virtual Environment**:
   ```bash
   cd TRINETRA
   python -m venv .venv
   # Windows PowerShell:
   .\.venv\Scripts\Activate.ps1
   # Linux / macOS:
   source .venv/bin/activate
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Initialize Database & Seed Scenarios**:
   ```bash
   python backend/init_db.py
   python -c "from backend.utils.data_seeder import seed_demo_dataset; seed_demo_dataset()"
   ```

4. **Launch Application**:
   ```bash
   python backend/app.py
   ```
   Access the dashboard at: **[http://127.0.0.1:5000](http://127.0.0.1:5000)**

---

## 🧪 Running Automated Tests

Run the full automated test suite (62 tests covering all 10 phases):

```bash
pytest tests/ -v
```

All 62 tests across Foundation, Core Inventory, Intelligence, Forecasting, Replenishment, Simulation, Decisions, Supply Network, Capital Optimization, and System Observability will execute in green.

---

## 📡 REST API Reference Summary

| Endpoint | Method | Description |
|---|---|---|
| `/api/system/health` | `GET` | Health probe verifying DB connectivity, uptime, and table counts |
| `/api/system/pulse` | `GET` | High-level operational pulse (SKUs, units, capital, alerts) |
| `/api/system/telemetry` | `GET` | Database storage footprint, table record counts, and event logs |
| `/api/system/drift` | `GET` | Statistical demand drift analysis across demand horizons |
| `/api/system/reconcile` | `POST` | Autonomous self-healing audit and repair trigger |
| `/api/system/circuit-breaker` | `GET` | Circuit breaker status (`CLOSED_NORMAL` vs `TRIPPED_SAFE_MODE`) |
| `/api/products` | `GET`, `POST` | Catalogue items CRUD and inventory filtering |
| `/api/inventory/movements` | `GET`, `POST` | Immutable stock movement ledger |
| `/api/suppliers` | `GET`, `POST` | Multi-tier vendor directory and reliability scoring |
| `/api/risks` | `GET` | 8D operational risk matrix and anomaly detection queue |
| `/api/forecasts/<id>` | `GET`, `POST` | Multi-model benchmark demand forecasts & champion retrain |
| `/api/replenishment/recommendations` | `GET` | Dynamic ROP/EOQ replenishment proposals |
| `/api/replenishment/purchase-orders` | `GET`, `POST` | Purchase order lifecycle management |
| `/api/simulation/run` | `POST` | Digital twin Monte Carlo stress-testing simulation |
| `/api/network/topology` | `GET` | 4-tier directed supply network graph topology |
| `/api/network/simulate-outage` | `POST` | Downstream blast radius outage impact simulation |
| `/api/capital/analytics` | `GET` | Working capital Pareto curve, ITR, DSI, and Gini coefficient |
| `/api/capital/rebalance` | `POST` | Multi-echelon buffer rebalancing optimization |
| `/api/capital/dead-stock-reclamation` | `GET` | 4-strategy dead stock liquidation playbook |
| `/api/decisions` | `GET`, `POST` | Human-in-the-loop decision ledger and overrides |
| `/api/decisions/outcomes` | `POST` | Closed-loop outcome verification tracking |

---

## 🛡️ License

Built for enterprise resilience and mission-critical supply networks. All rights reserved.
