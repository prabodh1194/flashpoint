"""Local development server — boots the Flashpoint gateway without AWS.

All DynamoDB operations use in-memory dicts. All ECS calls are no-ops.
Spark Connect is optional — if a local Spark Connect server is running,
wire it up; otherwise queries will fail but warehouse CRUD works.
"""

import os
import time

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
# ARNs are name-scoped so the Cost Center join (arn -> warehouse) works.
ecs_tasks.run_driver_task = lambda name: f'local-driver-{name}'  # ty: ignore[invalid-assignment]
ecs_tasks.wait_running = lambda arn: None  # ty: ignore[invalid-assignment]
ecs_tasks.private_ip = lambda arn: '127.0.0.1'  # ty: ignore[invalid-assignment]
ecs_tasks.run_executor_tasks = lambda master_url, count, name: [f'local-exec-{name}-{i}' for i in range(count)]  # ty: ignore[invalid-assignment]
ecs_tasks.is_running = lambda arn: True  # ty: ignore[invalid-assignment]
ecs_tasks.stop_tasks = lambda record: None  # ty: ignore[invalid-assignment]
ecs_tasks.launch_driver_with_executors = lambda name, executor_count, grpc_port: (  # ty: ignore[invalid-assignment]
    f'local-driver-{name}',
    '127.0.0.1',
    f'sc://127.0.0.1:{grpc_port}',
    [f'local-exec-{name}-{i}' for i in range(executor_count)],
)

# Mock DynamoDB store — use in-memory dicts
_db: dict[str, dict] = {}
_queries: dict[str, dict] = {}


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
store.put_warehouse_if_absent = _put_if_absent  # ty: ignore[invalid-assignment]
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


# Mock meters — in-memory accrual so the Cost Center view shows live data.
import datetime as _dt  # noqa: E402
import meters as _meters_mod  # noqa: E402

_meter_db: dict[tuple[str, str], dict] = {}


def _meter_accrue(warehouse_name: str, seconds: float, cost_usd: float) -> None:
    key = (warehouse_name, time.strftime('%Y-%m-%d'))
    row = _meter_db.setdefault(key, {'compute_seconds': 0.0, 'cost_usd': 0.0})
    row['compute_seconds'] += seconds
    row['cost_usd'] += cost_usd


def _meter_list(days: int = 30) -> dict[str, dict[str, dict]]:
    cutoff = time.strftime('%Y-%m-%d', time.localtime(time.time() - days * 86400))
    out: dict[str, dict[str, dict]] = {}
    for (name, day), row in _meter_db.items():
        if day >= cutoff:
            out.setdefault(name, {})[day] = dict(row)
    return out


_meters_mod.accrue = _meter_accrue  # ty: ignore[invalid-assignment]
_meters_mod.list_meters = _meter_list  # ty: ignore[invalid-assignment]


# Mock cost data — synthetic inventory + a deterministic history fused with
# the live in-memory meters so the Cost Center view has something to show.
import cost_data as _cost_data_mod  # noqa: E402


def _dt_from(ts: float | None):
    return _dt.datetime.fromtimestamp(ts) if ts else None


def _local_tasks() -> list[dict]:
    rows = []
    for wh in _db.values():
        if wh.get('status') == 'running' and wh.get('task_arn'):
            start = _dt_from(wh.get('session_started_at'))
            rows.append({
                'arn': wh['task_arn'], 'role': 'spark-connect',
                'capacity': 'FARGATE', 'cpu': '2048', 'memory': '8192',
                'started_at': start,
            })
            for arn in wh.get('executor_arns') or []:
                rows.append({
                    'arn': arn, 'role': 'spark-executor',
                    'capacity': 'FARGATE_SPOT', 'cpu': '2048', 'memory': '8192',
                    'started_at': start,
                })
    return rows


def _local_instances() -> list[dict]:
    return [{
        'id': 'i-local-gateway', 'type': 't4g.small', 'state': 'running',
        'launch_time': _dt.datetime.now() - _dt.timedelta(days=60),
        'tags': {'Name': 'flashpoint-local-gateway', 'Project': 'flashpoint'},
    }]


def _local_volumes() -> list[dict]:
    return [{'id': 'vol-local-root', 'state': 'in-use', 'size_gb': 20, 'type': 'gp3'}]


def _local_tagged() -> list[dict]:
    return [
        {'arn': 'arn:aws:dynamodb:us-east-1:000000000000:table/local-warehouses',
         'tags': {'Project': 'flashpoint'}},
        {'arn': 'arn:aws:dynamodb:us-east-1:000000000000:table/local-meters',
         'tags': {'Project': 'flashpoint'}},
        {'arn': 'arn:aws:logs:us-east-1:000000000000:log-group:/flashpoint/driver',
         'tags': {'Project': 'flashpoint'}},
        {'arn': 'arn:aws:s3:::local-bucket',
         'tags': {'Project': 'flashpoint'}},
    ]


def _local_daily(days: int = 30) -> list[dict]:
    """Deterministic 30-day history; today fused with the live meters."""
    today = _dt.date.today()
    out = []
    for i in range(days - 1, -1, -1):
        baseline = 0.08 + ((i * 7) % 10) * 0.02
        if i == 0:
            baseline += sum(r['cost_usd'] for r in _meter_db.values())
        out.append({'date': (today - _dt.timedelta(days=i)).isoformat(),
                    'total_usd': round(baseline, 4)})
    return out


_cost_data_mod.list_running_tasks = _local_tasks  # ty: ignore[invalid-assignment]
_cost_data_mod.list_instances = _local_instances  # ty: ignore[invalid-assignment]
_cost_data_mod.list_volumes = _local_volumes  # ty: ignore[invalid-assignment]
_cost_data_mod.list_tagged_resources = _local_tagged  # ty: ignore[invalid-assignment]
_cost_data_mod.get_daily_cost = _local_daily  # ty: ignore[invalid-assignment]


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
