import pytest
import json
from pathlib import Path
from services.agent_governance_service import AgentGovernanceService
from app import create_app
from init_db import initialize_database
from utils.data_seeder import seed_demo_dataset

BASE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def app_instance():
    test_db = BASE_DIR / "tests" / "test_agents.db"
    if test_db.exists():
        test_db.unlink()

    app = create_app("testing")
    app.config["DATABASE_PATH"] = str(test_db)

    with app.app_context():
        initialize_database(str(test_db))
        seed_demo_dataset(str(test_db))

    yield app

    if test_db.exists():
        try:
            test_db.unlink()
        except Exception:
            pass


@pytest.fixture(scope="module")
def client(app_instance):
    return app_instance.test_client()


class TestAgentGovernanceService:
    def test_autopilot_agent_execution_and_tool_traces(self, app_instance):
        db_path = app_instance.config["DATABASE_PATH"]
        service = AgentGovernanceService(db_path=db_path)
        result = service.run_replenishment_autopilot(service_level=0.95, max_budget_inr=1000000.0)

        assert "run_id" in result
        assert result["status"] == "COMPLETED"
        assert result["guardrail_decision"] in ["PASS", "HUMAN_OVERRIDE_ESCALATION"]
        assert len(result["tool_executions"]) >= 2
        
        # Verify tool trace structure
        tool_names = [t["tool_name"] for t in result["tool_executions"]]
        assert "circuit_breaker_check" in tool_names
        assert "generate_recommendations" in tool_names

        # Verify guardrail evaluation structure
        assert len(result["guardrail_evaluations"]) >= 1
        policy_names = [g["policy_name"] for g in result["guardrail_evaluations"]]
        assert "SystemCircuitBreakerPolicy" in policy_names

    def test_budget_ceiling_escalation_guardrail(self, app_instance):
        db_path = app_instance.config["DATABASE_PATH"]
        service = AgentGovernanceService(db_path=db_path)
        # Set max budget to ₹1 so that any replenishment triggers human override escalation
        result = service.run_replenishment_autopilot(service_level=0.95, max_budget_inr=1.0)

        assert "run_id" in result
        assert result["status"] == "COMPLETED"
        if len(result["actions_proposed"]) > 0:
            assert result["guardrail_decision"] == "HUMAN_OVERRIDE_ESCALATION"
            assert result["governance_mode"] == "HUMAN_APPROVAL_REQUIRED"

            budget_eval = [g for g in result["guardrail_evaluations"] if g["policy_name"] == "BudgetCeilingPolicy"]
            assert len(budget_eval) > 0
            assert budget_eval[0]["verdict"] == "HUMAN_OVERRIDE_ESCALATION"

    def test_shock_mitigation_failover_agent(self, app_instance):
        db_path = app_instance.config["DATABASE_PATH"]
        service = AgentGovernanceService(db_path=db_path)
        result = service.run_shock_mitigation_agent(supplier_id=1, lead_time_inflation_days=14)

        assert "run_id" in result
        assert result["agent_name"] == "ResilienceShockMitigatorAgent"
        assert result["status"] == "COMPLETED"
        assert isinstance(result["actions_proposed"], list)
        assert len(result["guardrail_evaluations"]) >= 1

    def test_agent_api_endpoints(self, client):
        # 1. Trigger Autopilot via API
        resp = client.post("/api/agents/autopilot/run", json={"service_level": 0.95, "max_budget_inr": 500000})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        run_id = data["data"]["run_id"]

        # 2. Query Agent Run Trace
        resp_run = client.get(f"/api/agents/runs/{run_id}")
        assert resp_run.status_code == 200
        data_run = resp_run.get_json()
        assert data_run["data"]["run_id"] == run_id
        assert "tool_executions" in data_run["data"]
        assert "guardrail_evaluations" in data_run["data"]

        # 3. List Agent Runs
        resp_list = client.get("/api/agents/runs")
        assert resp_list.status_code == 200
        data_list = resp_list.get_json()
        assert isinstance(data_list["data"]["runs"], list)
        assert len(data_list["data"]["runs"]) >= 1
