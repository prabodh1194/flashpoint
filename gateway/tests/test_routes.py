import json
import pytest
from unittest.mock import MagicMock, patch
import main
import ecs_tasks
import spark_client


@pytest.fixture(autouse=True)
def reset_state():
    main.warehouses.clear()
    main.query_history.clear()
    spark_client._cache.clear()


@pytest.fixture
def mock_create_warehouse_deps(monkeypatch, mock_ecs):
    monkeypatch.setattr(ecs_tasks, "run_driver_task", lambda: "arn:driver-1")
    monkeypatch.setattr(ecs_tasks, "wait_running", lambda arn: None)
    monkeypatch.setattr(ecs_tasks, "private_ip", lambda arn: "10.0.0.5")
    monkeypatch.setattr(ecs_tasks, "run_executor_tasks", lambda url, n: [f"arn:exec-{i}" for i in range(n)])


class TestHealthz:
    def test_health_ok(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "warehouses" in data


class TestCreateWarehouse:
    def test_creates_session_default_xs(self, client, mock_create_warehouse_deps, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "run_executor_tasks", lambda url, n: [f"arn:exec-{i}" for i in range(n)])
        monkeypatch.setattr(main.store, "put_warehouse", lambda name, record: None)

        resp = client.post("/warehouses", json={"name": "test-wh"})
        assert resp.status_code == 201
        data = resp.json()
        assert "name" in data
        assert data["status"] == "running"
        assert data["size"] == "XS"
        assert data["executor_count"] == 1
        assert data["endpoint"] == "sc://10.0.0.5:15002"

    def test_creates_session_custom_size(self, client, mock_create_warehouse_deps, monkeypatch):
        monkeypatch.setattr(main.store, "put_warehouse", lambda name, record: None)

        resp = client.post("/warehouses", json={"name": "test-wh", "size": "M"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["size"] == "M"
        assert data["executor_count"] == 4

    def test_rejects_unknown_size(self, client):
        resp = client.post("/warehouses", json={"name": "bad", "size": "XXL"})
        assert resp.status_code == 400

    def test_session_cap(self, client, monkeypatch):
        monkeypatch.setattr(main, "MAX_WAREHOUSES", 1)
        main.warehouses["existing"] = {"task_arn": "arn:existing"}
        resp = client.post("/warehouses", json={"name": "test-wh"})
        assert resp.status_code == 429

    def test_rejects_duplicate_name(self, client):
        main.warehouses["existing"] = {"task_arn": "arn:existing", "status": "running"}
        resp = client.post("/warehouses", json={"name": "existing", "size": "XS"})
        assert resp.status_code == 409


class TestListSessions:
    def test_empty(self, client):
        resp = client.get("/warehouses")
        assert resp.status_code == 200
        data = resp.json()
        assert data["warehouses"] == []
        assert data["count"] == 0

    def test_with_sessions(self, client):
        main.warehouses["s1"] = {"task_arn": "arn:1", "status": "running", "size": "XS", "executor_count": 1}
        main.warehouses["s2"] = {"task_arn": "arn:2", "status": "running", "size": "S", "executor_count": 2}
        resp = client.get("/warehouses")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["warehouses"]) == 2
        assert data["count"] == 2


class TestGetSession:
    def test_found_running(self, client, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "is_running", lambda arn: True)
        main.warehouses["s1"] = {
            "task_arn": "arn:1",
            "endpoint": "sc://10.0.0.5:15002",
            "status": "running",
            "size": "S",
            "executor_count": 2,
            "name": "my-wh",
        }
        resp = client.get("/warehouses/s1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "s1"
        assert data["status"] == "running"

    def test_not_found(self, client):
        resp = client.get("/warehouses/nonexistent")
        assert resp.status_code == 404

    def test_suspended_session(self, client, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "is_running", lambda arn: False)
        main.warehouses["s1"] = {
            "task_arn": "",
            "endpoint": None,
            "status": "suspended",
            "size": "XS",
            "executor_count": 1,
        }
        resp = client.get("/warehouses/s1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "suspended"


class TestRunQuery:
    @pytest.fixture(autouse=True)
    def setup_session(self, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "is_running", lambda arn: True)
        main.warehouses["s1"] = {
            "task_arn": "arn:driver",
            "task_ip": "10.0.0.5",
            "endpoint": "sc://10.0.0.5:15002",
            "status": "running",
        }

    def test_runs_query(self, client, monkeypatch):
        mock_spark = MagicMock()
        mock_df = MagicMock()
        mock_df.columns = ["id", "name"]
        mock_df.collect.return_value = [["1", "alice"]]
        mock_spark.sql.return_value = mock_df
        monkeypatch.setattr(spark_client, "get", lambda wid, ep: mock_spark)
        monkeypatch.setattr(main, "_sql_execution_ids", lambda s: set())
        monkeypatch.setattr(main, "_fetch_query_dag", lambda s, b: None)

        resp = client.post("/warehouses/s1/query", json={"sql": "SELECT 1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["columns"] == ["id", "name"]
        assert data["row_count"] == 1
        assert len(data["query_id"]) == 16

    def test_session_not_found(self, client):
        resp = client.post("/warehouses/s99/query", json={"sql": "SELECT 1"})
        assert resp.status_code == 404

    def test_session_not_running(self, client, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "is_running", lambda arn: False)
        resp = client.post("/warehouses/s1/query", json={"sql": "SELECT 1"})
        assert resp.status_code == 409

    def test_spark_error_returned_as_400(self, client, monkeypatch):
        mock_spark = MagicMock()
        mock_spark.sql.side_effect = Exception("table not found: bad_table")
        monkeypatch.setattr(spark_client, "get", lambda wid, ep: mock_spark)
        monkeypatch.setattr(main, "_sql_execution_ids", lambda s: set())

        resp = client.post("/warehouses/s1/query", json={"sql": "SELECT * FROM bad_table"})
        assert resp.status_code == 400

    def test_records_failed_query_in_history(self, client, monkeypatch):
        mock_spark = MagicMock()
        mock_spark.sql.side_effect = Exception("fail")
        monkeypatch.setattr(spark_client, "get", lambda wid, ep: mock_spark)
        monkeypatch.setattr(main, "_sql_execution_ids", lambda s: set())

        client.post("/warehouses/s1/query", json={"sql": "bad"})
        assert len(main.query_history) == 1
        assert main.query_history[0]["status"] == "failed"


class TestDeleteSession:
    def test_deletes_session(self, client, monkeypatch):
        monkeypatch.setattr(spark_client, "drop", lambda name: None)
        monkeypatch.setattr(ecs_tasks, "stop_tasks", lambda s: None)
        monkeypatch.setattr(main.store, "delete_warehouse", lambda name: None)
        main.warehouses["s1"] = {"task_arn": "arn:d", "executor_arns": []}

        resp = client.delete("/warehouses/s1")
        assert resp.status_code == 204
        assert "s1" not in main.warehouses

    def test_not_found(self, client):
        resp = client.delete("/warehouses/nonexistent")
        assert resp.status_code == 404


class TestSuspendResume:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        monkeypatch.setattr(spark_client, "drop", lambda name: None)
        monkeypatch.setattr(ecs_tasks, "stop_tasks", lambda s: None)
        monkeypatch.setattr(main.store, "update_warehouse_status", lambda *a, **kw: None)
        monkeypatch.setattr(main.store, "put_warehouse", lambda name, record: None)
        main.warehouses["s1"] = {
            "task_arn": "arn:d",
            "executor_arns": ["arn:e1"],
            "task_ip": "10.0.0.5",
            "endpoint": "sc://10.0.0.5:15002",
            "status": "running",
            "size": "S",
            "executor_count": 2,
        }

    def test_suspend_running_session(self, client):
        resp = client.post("/warehouses/s1/suspend")
        assert resp.status_code == 200
        assert resp.json()["status"] == "suspended"
        assert main.warehouses["s1"]["status"] == "suspended"

    def test_suspend_already_suspended(self, client):
        main.warehouses["s1"]["status"] = "suspended"
        resp = client.post("/warehouses/s1/suspend")
        assert resp.status_code == 200

    def test_suspend_not_found(self, client):
        resp = client.post("/warehouses/nonexistent/suspend")
        assert resp.status_code == 404

    def test_resume_suspended(self, client, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "run_driver_task", lambda: "arn:new-driver")
        monkeypatch.setattr(ecs_tasks, "wait_running", lambda arn: None)
        monkeypatch.setattr(ecs_tasks, "private_ip", lambda arn: "10.0.0.6")
        monkeypatch.setattr(ecs_tasks, "run_executor_tasks", lambda url, n: [f"arn:new-exec-{i}" for i in range(n)])

        main.warehouses["s1"]["status"] = "suspended"
        resp = client.post("/warehouses/s1/resume")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["endpoint"] == "sc://10.0.0.6:15002"

    def test_resume_already_running(self, client):
        resp = client.post("/warehouses/s1/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"


class TestResize:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "is_running", lambda arn: True)
        monkeypatch.setattr(main.store, "update_warehouse_status", lambda *a, **kw: None)
        main.warehouses["s1"] = {
            "task_arn": "arn:d",
            "executor_arns": ["arn:e1", "arn:e2"],
            "task_ip": "10.0.0.5",
            "endpoint": "sc://10.0.0.5:15002",
            "status": "running",
            "size": "S",
            "executor_count": 2,
        }

    def test_scale_up(self, client, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "run_executor_tasks", lambda url, n: [f"arn:new-{i}" for i in range(n)])
        resp = client.post("/warehouses/s1/resize", json={"name": "test-wh", "size": "M"})
        assert resp.status_code == 200
        assert main.warehouses["s1"]["executor_count"] == 4
        assert main.warehouses["s1"]["size"] == "M"

    def test_scale_down(self, client, mock_ecs):
        resp = client.post("/warehouses/s1/resize", json={"size": "XS"})
        assert resp.status_code == 200
        assert main.warehouses["s1"]["executor_count"] == 1
        assert main.warehouses["s1"]["size"] == "XS"

    def test_unknown_size(self, client):
        resp = client.post("/warehouses/s1/resize", json={"name": "bad", "size": "XXL"})
        assert resp.status_code == 400

    def test_session_not_running(self, client):
        main.warehouses["s1"]["status"] = "suspended"
        resp = client.post("/warehouses/s1/resize", json={"name": "test-wh", "size": "M"})
        assert resp.status_code == 409


class TestHistory:
    def test_empty(self, client):
        resp = client.get("/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["history"] == []
        assert data["count"] == 0

    def test_with_entries(self, client):
        main.query_history.append({
            "query_id": "abc123",
            "sql": "SELECT 1",
            "status": "success",
            "duration_ms": 100,
            "row_count": 1,
            "name": "s1",
            "ts": "12:00:00",
        })
        resp = client.get("/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["history"]) == 1

    def test_history_entry_found(self, client):
        main.query_history.append({"query_id": "abc", "sql": "SELECT 1"})
        resp = client.get("/history/abc")
        assert resp.status_code == 200

    def test_history_entry_not_found(self, client):
        resp = client.get("/history/nonexistent")
        assert resp.status_code == 404
