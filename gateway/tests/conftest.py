import os

import pytest

os.environ.setdefault('FLASHPOINT_ECS_CLUSTER', 'test-cluster')
os.environ.setdefault('FLASHPOINT_DRIVER_TASK_DEF', 'test-driver-td')
os.environ.setdefault('FLASHPOINT_EXECUTOR_TASK_DEF', 'test-executor-td')
os.environ.setdefault('FLASHPOINT_SUBNETS', 'subnet-a,subnet-b,subnet-c')
os.environ.setdefault('FLASHPOINT_SECURITY_GROUP', 'sg-test')
os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')
os.environ.setdefault('FLASHPOINT_WAREHOUSES_TABLE', 'test-warehouses')
os.environ.setdefault('FLASHPOINT_METERS_TABLE', 'test-meters')

from unittest.mock import MagicMock, patch

_boto3_client_patch = patch('boto3.client', return_value=MagicMock())
_boto3_resource_patch = patch('boto3.resource', return_value=MagicMock())
_boto3_client_patch.start()
_boto3_resource_patch.start()

import ecs_tasks
import main
import store


@pytest.fixture
def mock_ecs(monkeypatch):
    client = MagicMock()
    client.run_task.return_value = {
        'tasks': [{'taskArn': 'arn:aws:ecs:us-east-1:123456789:task/test-cluster/abc123'}],
        'failures': [],
    }
    client.describe_tasks.return_value = {
        'tasks': [
            {
                'taskArn': 'arn:aws:ecs:us-east-1:123456789:task/test-cluster/abc123',
                'lastStatus': 'RUNNING',
                'attachments': [
                    {
                        'details': [
                            {'name': 'privateIPv4Address', 'value': '10.0.0.5'},
                        ],
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(ecs_tasks, 'ecs', client)
    return client


@pytest.fixture
def mock_store():
    """Replace store with an in-memory dict, simulating DynamoDB."""
    _db: dict[str, dict] = {}

    def _get(name: str) -> dict | None:
        return _db.get(name)

    def _put(name: str, item: dict) -> None:
        _db[name] = {**item, 'name': name}

    def _put_if_absent(name: str, item: dict) -> bool:
        if name in _db:
            return False
        _db[name] = {**item, 'name': name}
        return True

    def _update(name: str, status: str, **extra) -> None:
        if name in _db:
            _db[name]['status'] = status
            _db[name].update(extra)

    def _delete(name: str) -> None:
        _db.pop(name, None)

    def _list() -> list[dict]:
        return list(_db.values())

    def _count_running() -> int:
        return sum(1 for v in _db.values() if v.get('status') == 'running')

    store.get_warehouse = _get  # ty: ignore
    store.put_warehouse = _put  # ty: ignore
    store.put_warehouse_if_absent = _put_if_absent  # ty: ignore
    store.update_warehouse_status = _update  # ty: ignore
    store.delete_warehouse = _delete  # ty: ignore
    store.list_warehouses = _list  # ty: ignore
    store.count_running_warehouses = _count_running  # ty: ignore

    # Query record store
    _queries: dict[str, dict] = {}

    def _put_query(qid: str, record: dict) -> None:
        _queries[qid] = {**record, 'qid': qid}

    def _get_query(qid: str) -> dict | None:
        return _queries.get(qid)

    def _update_query(qid: str, status: str, **extra) -> None:
        if qid in _queries:
            _queries[qid]['status'] = status
            _queries[qid].update(extra)

    def _list_queries() -> list[dict]:
        return list(_queries.values())

    store.put_query_record = _put_query  # ty: ignore
    store.get_query_record = _get_query  # ty: ignore
    store.update_query_status = _update_query  # ty: ignore
    store.list_query_records = _list_queries  # ty: ignore

    return _db, _queries

    return _db


@pytest.fixture
def app():
    return main.app


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)
