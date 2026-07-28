import json
import pytest
from unittest.mock import MagicMock, patch
import main
import ecs_tasks
import spark_client


@pytest.fixture(autouse=True)
def reset_state():
    main.sessions.clear()
    main.query_history.clear()
    spark_client._cache.clear()


@pytest.fixture
def mock_create_session_deps(monkeypatch, mock_ecs):
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
        assert "sessions" in data


class TestCreateSession:
    def test_creates_session_default_xs(self, client, mock_create_session_deps, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "run_executor_tasks", lambda url, n: [f"arn:exec-{i}" for i in range(n)])
        monkeypatch.setattr(main.store, "put_session", lambda sid, record: None)

        resp = client.post("/sessions", json={})
        assert resp.status_code == 201
        data = resp.json()
        assert "session_id" in data
        assert data["status"] == "running"
        assert data["size"] == "XS"
        assert data["executor_count"] == 1
        assert data["endpoint"] == "sc://10.0.0.5:15002"

    def test_creates_session_custom_size(self, client, mock_create_session_deps, monkeypatch):
        monkeypatch.setattr(main.store, "put_session", lambda sid, record: None)

        resp = client.post("/sessions", json={"size": "M"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["size"] == "M"
        assert data["executor_count"] == 4

    def test_rejects_unknown_size(self, client):
        resp = client.post("/sessions", json={"size": "XXL"})
        assert resp.status_code == 400

    def test_session_cap(self, client, monkeypatch):
        monkeypatch.setattr(main, "MAX_SESSIONS", 1)
        main.sessions["existing"] = {"task_arn": "arn:existing"}
        resp = client.post("/sessions", json={})
        assert resp.status_code == 429


class TestListSessions:
    def test_empty(self, client):
        resp = client.get("/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []
        assert data["count"] == 0

    def test_with_sessions(self, client):
        main.sessions["s1"] = {"task_arn": "arn:1"}
        main.sessions["s2"] = {"task_arn": "arn:2"}
        resp = client.get("/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) == 2
        assert data["count"] == 2


class TestGetSession:
    def test_found_running(self, client, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "is_running", lambda arn: True)
        main.sessions["s1"] = {
            "task_arn": "arn:1",
            "endpoint": "sc://10.0.0.5:15002",
            "status": "running",
            "size": "S",
            "executor_count": 2,
            "name": "my-wh",
        }
        resp = client.get("/sessions/s1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "s1"
        assert data["status"] == "running"

    def test_not_found(self, client):
        resp = client.get("/sessions/nonexistent")
        assert resp.status_code == 404

    def test_suspended_session(self, client, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "is_running", lambda arn: False)
        main.sessions["s1"] = {
            "task_arn": "",
            "endpoint": None,
            "status": "suspended",
            "size": "XS",
            "executor_count": 1,
        }
        resp = client.get("/sessions/s1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "suspended"


class TestRunQuery:
    @pytest.fixture(autouse=True)
    def setup_session(self, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "is_running", lambda arn: True)
        main.sessions["s1"] = {
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
        monkeypatch.setattr(spark_client, "get", lambda sid, ep: mock_spark)
        monkeypatch.setattr(main, "_sql_execution_ids", lambda s: set())
        monkeypatch.setattr(main, "_fetch_query_dag", lambda s, b: None)

        resp = client.post("/sessions/s1/query", json={"sql": "SELECT 1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["columns"] == ["id", "name"]
        assert data["row_count"] == 1
        assert len(data["query_id"]) == 16

    def test_session_not_found(self, client):
        resp = client.post("/sessions/s99/query", json={"sql": "SELECT 1"})
        assert resp.status_code == 404

    def test_session_not_running(self, client, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "is_running", lambda arn: False)
        resp = client.post("/sessions/s1/query", json={"sql": "SELECT 1"})
        assert resp.status_code == 409

    def test_spark_error_returned_as_400(self, client, monkeypatch):
        mock_spark = MagicMock()
        mock_spark.sql.side_effect = Exception("table not found: bad_table")
        monkeypatch.setattr(spark_client, "get", lambda sid, ep: mock_spark)
        monkeypatch.setattr(main, "_sql_execution_ids", lambda s: set())

        resp = client.post("/sessions/s1/query", json={"sql": "SELECT * FROM bad_table"})
        assert resp.status_code == 400

    def test_records_failed_query_in_history(self, client, monkeypatch):
        mock_spark = MagicMock()
        mock_spark.sql.side_effect = Exception("fail")
        monkeypatch.setattr(spark_client, "get", lambda sid, ep: mock_spark)
        monkeypatch.setattr(main, "_sql_execution_ids", lambda s: set())

        client.post("/sessions/s1/query", json={"sql": "bad"})
        assert len(main.query_history) == 1
        assert main.query_history[0]["status"] == "failed"


class TestDeleteSession:
    def test_deletes_session(self, client, monkeypatch):
        monkeypatch.setattr(spark_client, "drop", lambda sid: None)
        monkeypatch.setattr(ecs_tasks, "stop_tasks", lambda s: None)
        monkeypatch.setattr(main.store, "delete_session", lambda sid: None)
        main.sessions["s1"] = {"task_arn": "arn:d", "executor_arns": []}

        resp = client.delete("/sessions/s1")
        assert resp.status_code == 204
        assert "s1" not in main.sessions

    def test_not_found(self, client):
        resp = client.delete("/sessions/nonexistent")
        assert resp.status_code == 404


class TestSuspendResume:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        monkeypatch.setattr(spark_client, "drop", lambda sid: None)
        monkeypatch.setattr(ecs_tasks, "stop_tasks", lambda s: None)
        monkeypatch.setattr(main.store, "update_session_status", lambda *a, **kw: None)
        monkeypatch.setattr(main.store, "put_session", lambda sid, record: None)
        main.sessions["s1"] = {
            "task_arn": "arn:d",
            "executor_arns": ["arn:e1"],
            "task_ip": "10.0.0.5",
            "endpoint": "sc://10.0.0.5:15002",
            "status": "running",
            "size": "S",
            "executor_count": 2,
        }

    def test_suspend_running_session(self, client):
        resp = client.post("/sessions/s1/suspend")
        assert resp.status_code == 200
        assert resp.json()["status"] == "suspended"
        assert main.sessions["s1"]["status"] == "suspended"

    def test_suspend_already_suspended(self, client):
        main.sessions["s1"]["status"] = "suspended"
        resp = client.post("/sessions/s1/suspend")
        assert resp.status_code == 200

    def test_suspend_not_found(self, client):
        resp = client.post("/sessions/nonexistent/suspend")
        assert resp.status_code == 404

    def test_resume_suspended(self, client, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "run_driver_task", lambda: "arn:new-driver")
        monkeypatch.setattr(ecs_tasks, "wait_running", lambda arn: None)
        monkeypatch.setattr(ecs_tasks, "private_ip", lambda arn: "10.0.0.6")
        monkeypatch.setattr(ecs_tasks, "run_executor_tasks", lambda url, n: [f"arn:new-exec-{i}" for i in range(n)])

        main.sessions["s1"]["status"] = "suspended"
        resp = client.post("/sessions/s1/resume")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["endpoint"] == "sc://10.0.0.6:15002"

    def test_resume_already_running(self, client):
        resp = client.post("/sessions/s1/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"


class TestResize:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        monkeypatch.setattr(ecs_tasks, "is_running", lambda arn: True)
        monkeypatch.setattr(main.store, "update_session_status", lambda *a, **kw: None)
        main.sessions["s1"] = {
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
        resp = client.post("/sessions/s1/resize", json={"size": "M"})
        assert resp.status_code == 200
        assert main.sessions["s1"]["executor_count"] == 4
        assert main.sessions["s1"]["size"] == "M"

    def test_scale_down(self, client, mock_ecs):
        resp = client.post("/sessions/s1/resize", json={"size": "XS"})
        assert resp.status_code == 200
        assert main.sessions["s1"]["executor_count"] == 1
        assert main.sessions["s1"]["size"] == "XS"

    def test_unknown_size(self, client):
        resp = client.post("/sessions/s1/resize", json={"size": "XXL"})
        assert resp.status_code == 400

    def test_session_not_running(self, client):
        main.sessions["s1"]["status"] = "suspended"
        resp = client.post("/sessions/s1/resize", json={"size": "M"})
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
            "session_id": "s1",
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
