"""DynamoDB-backed warehouse store.

The single source of truth for all warehouse state. Gateway instances
read and write directly — there is no in-memory cache to keep in sync.
"""

import os
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr

_TABLE_NAME = os.environ.get('FLASHPOINT_WAREHOUSES_TABLE', 'flashpoint-dev-warehouses')
_dynamodb = boto3.resource('dynamodb')


def _table():
    return _dynamodb.Table(_TABLE_NAME)


# --- Decimal/float conversion ---
# DynamoDB stores numbers as Decimal; float is not supported. Centralised here so
# created_at / cost_usd / etc. round-trip without precision drift.


def _to_ddb(v):
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, list):
        return [_to_ddb(i) for i in v]
    if isinstance(v, dict):
        return {k: _to_ddb(val) for k, val in v.items()}
    return v


def _from_ddb(v):
    if isinstance(v, Decimal):
        f = float(v)
        return int(f) if f == int(f) else f
    if isinstance(v, list):
        return [_from_ddb(i) for i in v]
    if isinstance(v, dict):
        return {k: _from_ddb(val) for k, val in v.items()}
    return v


# --- Commands ---


def put_warehouse(name: str, item: dict) -> None:
    """Write (or overwrite) a complete session record to DynamoDB."""
    record = {'name': name, 'updated_at': Decimal(str(time.time()))}
    record.update(_to_ddb(item))
    _table().put_item(Item=record)


def update_warehouse_status(name: str, status: str, **extra) -> None:
    """Update status + optional extra fields without overwriting the whole record."""
    expr_parts = ['#st = :status', 'updated_at = :ts']
    names = {'#st': 'status'}
    values = {':status': status, ':ts': Decimal(str(time.time()))}
    for k, v in extra.items():
        expr_parts.append(f'#{k} = :{k}')
        names[f'#{k}'] = k
        values[f':{k}'] = _to_ddb(v)
    _table().update_item(
        Key={'name': name},
        UpdateExpression='SET ' + ', '.join(expr_parts),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def delete_warehouse(name: str) -> None:
    """Remove a warehouse record from DynamoDB permanently."""
    _table().delete_item(Key={'name': name})


# --- Queries ---


def get_warehouse(name: str) -> dict | None:
    resp = _table().get_item(Key={'name': name})
    item = resp.get('Item')
    return _from_ddb(item) if item else None


def list_warehouses() -> list[dict]:
    resp = _table().scan()
    return [_from_ddb(item) for item in resp.get('Items', [])]


def count_running_warehouses() -> int:
    """Return the number of warehouses with status = 'running'.

    Uses a DynamoDB scan with FilterExpression — the count only reads
    matching items, not the full dataset. Scan is fine for the expected
    scale (MAX_WAREHOUSES is ~3 in dev, maybe 10 in production).
    """
    resp = _table().scan(
        FilterExpression=Attr('status').eq('running'),
        Select='COUNT',
    )
    return resp.get('Count', 0)
