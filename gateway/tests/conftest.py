import os
import pytest

os.environ.setdefault("FLASHPOINT_ECS_CLUSTER", "test-cluster")
os.environ.setdefault("FLASHPOINT_DRIVER_TASK_DEF", "test-driver-td")
os.environ.setdefault("FLASHPOINT_EXECUTOR_TASK_DEF", "test-executor-td")
os.environ.setdefault("FLASHPOINT_SUBNETS", "subnet-a,subnet-b,subnet-c")
os.environ.setdefault("FLASHPOINT_SECURITY_GROUP", "sg-test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("FLASHPOINT_SESSIONS_TABLE", "test-sessions")
os.environ.setdefault("FLASHPOINT_METERS_TABLE", "test-meters")

import boto3
from unittest.mock import patch, MagicMock

_boto3_client_patch = patch("boto3.client", return_value=MagicMock())
_boto3_resource_patch = patch("boto3.resource", return_value=MagicMock())
_boto3_client_patch.start()
_boto3_resource_patch.start()

import main
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
    # Also patch main for any remaining direct references
    return client


@pytest.fixture
def app():
    return main.app


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)
