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

import ecs_tasks  # noqa: E402
import store  # noqa: E402

# Mock ECS operations
ecs_tasks.run_driver_task = lambda: 'local-driver-arn'  # ty: ignore[invalid-assignment]
ecs_tasks.wait_running = lambda arn: None  # ty: ignore[invalid-assignment]
ecs_tasks.private_ip = lambda arn: '127.0.0.1'  # ty: ignore[invalid-assignment]
ecs_tasks.run_executor_tasks = lambda master_url, count: [f'local-exec-{i}' for i in range(count)]  # ty: ignore[invalid-assignment]
ecs_tasks.is_running = lambda arn: True  # ty: ignore[invalid-assignment]
ecs_tasks.stop_tasks = lambda record: None  # ty: ignore[invalid-assignment]
ecs_tasks.launch_driver_with_executors = lambda executor_count, grpc_port: (  # ty: ignore[invalid-assignment]
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


store.get_warehouse = _get  # ty: ignore[invalid-assignment]
store.put_warehouse = _put  # ty: ignore[invalid-assignment]
store.update_warehouse_status = _update  # ty: ignore[invalid-assignment]
store.delete_warehouse = _delete  # ty: ignore[invalid-assignment]
store.list_warehouses = _list  # ty: ignore[invalid-assignment]
store.count_running_warehouses = _count_running  # ty: ignore[invalid-assignment]
store.put_query_record = _put_query  # ty: ignore[invalid-assignment]
store.get_query_record = _get_query  # ty: ignore[invalid-assignment]
store.update_query_status = _update_query  # ty: ignore[invalid-assignment]
store.list_query_records = _list_queries  # ty: ignore[invalid-assignment]

# Mock reconcile
import reconcile as _reconcile_mod  # noqa: E402

_reconcile_mod.reconcile = lambda cluster: None  # ty: ignore[invalid-assignment]


# Boot uvicorn
import uvicorn  # noqa: E402

from main import app  # noqa: E402

print('─' * 50)
print('Flashpoint local dev server')
print('─' * 50)
print('  Gateway:  http://localhost:8080')
print('  Health:   http://localhost:8080/healthz')
print('  Docs:     http://localhost:8080/docs')
print()
print('All AWS calls mocked. DynamoDB is in-memory.')
print('Warehouse CRUD works. Queries need a local')
print('Spark Connect server on :15002.')
print('─' * 50)

uvicorn.run(app, host='0.0.0.0', port=8080, log_level='info')
