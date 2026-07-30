"""Local development server — boots the Flashpoint gateway without AWS.

All DynamoDB operations use in-memory dicts. All ECS calls are no-ops.
Spark Connect is optional — if a local Spark Connect server is running,
wire it up; otherwise queries will fail but warehouse CRUD works.
"""

import os

os.environ.setdefault('FLASHPOINT_ECS_CLUSTER', 'local')
os.environ.setdefault('FLASHPOINT_DRIVER_TASK_DEF', 'local-driver')
os.environ.setdefault('FLASHPOINT_EXECUTOR_TASK_DEF', 'local-executor')
os.environ.setdefault('FLASHPOINT_SUBNETS', 'local')
os.environ.setdefault('FLASHPOINT_SECURITY_GROUP', 'local')
os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')
os.environ.setdefault('FLASHPOINT_WAREHOUSES_TABLE', 'local-warehouses')
os.environ.setdefault('FLASHPOINT_METERS_TABLE', 'local-meters')
os.environ.setdefault('FLASHPOINT_QUERIES_TABLE', 'local-queries')
os.environ.setdefault('FLASHPOINT_QUERY_RESULTS_BUCKET', 'local-bucket')
os.environ.setdefault('AWS_ACCESS_KEY_ID', 'local')
os.environ.setdefault('AWS_SECRET_ACCESS_KEY', 'local')

from unittest.mock import MagicMock, patch

_boto3_client_patch = patch('boto3.client', return_value=MagicMock())
_boto3_resource_patch = patch('boto3.resource', return_value=MagicMock())
_boto3_client_patch.start()
_boto3_resource_patch.start()

import ecs_tasks
import store

# Mock ECS operations
ecs_tasks.run_driver_task = lambda: 'local-driver-arn'
ecs_tasks.wait_running = lambda arn: None
ecs_tasks.private_ip = lambda arn: '127.0.0.1'
ecs_tasks.run_executor_tasks = lambda master_url, count: [f'local-exec-{i}' for i in range(count)]
ecs_tasks.is_running = lambda arn: True
ecs_tasks.stop_tasks = lambda record: None
ecs_tasks.launch_driver_with_executors = lambda executor_count, grpc_port: (
    'local-driver-arn',
    '127.0.0.1',
    f'sc://127.0.0.1:{grpc_port}',
    [f'local-exec-{i}' for i in range(executor_count)],
)

# Mock DynamoDB store — use in-memory dicts
_db: dict[str, dict] = {}
_queries: dict[str, dict] = {}


def _get(name: str) -> dict | None:
    return _db.get(name)


def _put(name: str, item: dict) -> None:
    _db[name] = {**item, 'name': name}


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


store.get_warehouse = _get
store.put_warehouse = _put
store.update_warehouse_status = _update
store.delete_warehouse = _delete
store.list_warehouses = _list
store.count_running_warehouses = _count_running
store.put_query_record = _put_query
store.get_query_record = _get_query
store.update_query_status = _update_query
store.list_query_records = _list_queries

# Mock reconcile
import reconcile as _reconcile_mod

_reconcile_mod.reconcile = lambda cluster: None


# Boot uvicorn
import uvicorn
from main import app

print('─' * 50)
print('Flashpoint local dev server')
print('─' * 50)
print(f'  Gateway:  http://localhost:8080')
print(f'  Health:   http://localhost:8080/healthz')
print(f'  Docs:     http://localhost:8080/docs')
print()
print('All AWS calls mocked. DynamoDB is in-memory.')
print('Warehouse CRUD works. Queries need a local')
print('Spark Connect server on :15002.')
print('─' * 50)

uvicorn.run(app, host='0.0.0.0', port=8080, log_level='info')
