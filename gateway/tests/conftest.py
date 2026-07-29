import os
import pytest

os.environ.setdefault("FLASHPOINT_ECS_CLUSTER", "test-cluster")
os.environ.setdefault("FLASHPOINT_DRIVER_TASK_DEF", "test-driver-td")
os.environ.setdefault("FLASHPOINT_EXECUTOR_TASK_DEF", "test-executor-td")
os.environ.setdefault("FLASHPOINT_SUBNETS", "subnet-a,subnet-b,subnet-c")
os.environ.setdefault("FLASHPOINT_SECURITY_GROUP", "sg-test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("FLASHPOINT_WAREHOUSES_TABLE", "test-warehouses")
os.environ.setdefault("FLASHPOINT_METERS_TABLE", "test-meters")

import boto3
from unittest.mock import patch, MagicMock

_boto3_client_patch = patch("boto3.client", return_value=MagicMock())
_boto3_resource_patch = patch("boto3.resource", return_value=MagicMock())
_boto3_client_patch.start()
_boto3_resource_patch.start()

import main
import store
import ecs_tasks
import spark_client


@pytest.fixture
def mock_ecs(monkeypatch):
    client = MagicMock()
    client.run_task.return_value = {
        "tasks": [{"taskArn": "arn:aws:ecs:us-east-1:123456789:task/test-cluster/abc123"}],
        "failures": [],
    }
    client.describe_tasks.return_value = {
        "tasks": [{
            "taskArn": "arn:aws:ecs:us-east-1:123456789:task/test-cluster/abc123",
            "lastStatus": "RUNNING",
            "attachments": [{
                "details": [
                    {"name": "privateIPv4Address", "value": "10.0.0.5"},
                ],
            }],
        }],
    }
    monkeypatch.setattr(ecs_tasks, "ecs", client)
    return client


@pytest.fixture
def mock_store():
    """Replace store with an in-memory dict, simulating DynamoDB."""
    _db: dict[str, dict] = {}

    def _get(name):
        return _db.get(name)

    def _put(name, record):
        _db[name] = {**record, "name": name}

    def _update(name, status, **extra):
        if name in _db:
            _db[name]["status"] = status
            _db[name].update(extra)

    def _delete(name):
        _db.pop(name, None)

    def _list():
        return list(_db.values())

    store.get_warehouse = _get
    store.put_warehouse = _put
    store.update_warehouse_status = _update
    store.delete_warehouse = _delete
    store.list_warehouses = _list

    return _db


@pytest.fixture
def app():
    return main.app


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)
