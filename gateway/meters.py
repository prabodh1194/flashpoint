"""Meter writer — compute-second + cost accounting into the meters table.

Durable per-warehouse per-day accumulator, written with DynamoDB atomic ADD
so concurrent gateway instances never lose counts (no read-modify-write).

Schema (table provisioned in infra/dynamodb.tf):
  pk = wh:{warehouse_name}
  sk = day:{YYYY-MM-DD}
  attrs: compute_seconds (N), cost_usd (N)

Costs derive from HOURLY_RATE x elapsed wall-clock per warehouse session.
The gateway only bills for the time a warehouse is actually running —
suspended warehouses cost $0, matching the Snowflake pricing model.
"""

import logging
import time
from decimal import Decimal

import boto3

from config import HOURLY_RATE, METERS_TABLE

log = logging.getLogger(__name__)

_dynamodb = boto3.resource('dynamodb')


def _table():
    return _dynamodb.Table(METERS_TABLE)


def day_key() -> str:
    return time.strftime('%Y-%m-%d', time.localtime(time.time()))


def accrue(warehouse_name: str, seconds: float, cost_usd: float) -> None:
    """Atomically add a compute/cost chunk to the current day's meter."""
    try:
        _table().update_item(
            Key={'pk': f'wh:{warehouse_name}', 'sk': f'day:{day_key()}'},
            UpdateExpression='ADD compute_seconds :s, cost_usd :c',
            ExpressionAttributeValues={
                ':s': Decimal(str(seconds)),
                ':c': Decimal(str(cost_usd)),
            },
        )
    except Exception as exc:
        log.error('Meter accrue failed for %s: %s', warehouse_name, exc)


def accrue_session(record: dict, now: float | None = None) -> float:
    """Bill a warehouse session window since the last meter checkpoint.

    The record carries `session_started_at` (session open) and
    `last_metered_at` (last checkpoint). Each call accrues the delta since
    the last checkpoint, so heartbeat ticks + finalize never double-count.

    Returns the number of seconds accrued (0 if nothing to bill).
    """
    checkpoint = record.get('last_metered_at') or record.get('session_started_at')
    if not checkpoint:
        return 0
    now = now or time.time()
    if now <= checkpoint:
        return 0
    seconds = now - checkpoint
    rate = HOURLY_RATE.get(record.get('size', 'XS'), HOURLY_RATE['XS'])
    accrue(record['name'], seconds, seconds / 3600 * rate)
    return seconds


def list_meters(days: int = 30) -> dict[str, dict[str, dict]]:
    """Return all meter entries as {warehouse: {day: {compute_seconds, cost_usd}}}.

    Small dataset (per-warehouse per-day rows); scan is fine at this scale.
    """
    resp = _table().scan()
    out: dict[str, dict[str, dict]] = {}
    for item in resp.get('Items', []):
        pk: str = item['pk']
        sk: str = item['sk']
        if not pk.startswith('wh:') or not sk.startswith('day:'):
            continue
        wh = pk[3:]
        day = sk[4:]
        out.setdefault(wh, {})[day] = {
            'compute_seconds': float(item.get('compute_seconds', 0)),
            'cost_usd': float(item.get('cost_usd', 0)),
        }
    return out
