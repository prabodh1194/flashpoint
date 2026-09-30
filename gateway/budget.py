"""Gateway-side Spark spend guard — see docs/try-it-design.md §3.2.

Month-to-date Spark spend comes from the meters table (accrued at real
on-demand rates). A durable kill switch lives next to it so every gateway
instance sees the same state. The ceiling covers the Spark envelope only;
the fixed idle infra is assumed already spent.
"""

import logging
import time
from decimal import Decimal

import boto3

import meters
from config import METERS_TABLE, SPARK_BUDGET_MARGIN_USD, SPARK_BUDGET_USD

log = logging.getLogger(__name__)

_dynamodb = boto3.resource('dynamodb')

_KILL_SWITCH_KEY = {'pk': 'budget', 'sk': 'state'}


def _table():
    return _dynamodb.Table(METERS_TABLE)


def month_spend_usd(now: float | None = None) -> float:
    """Sum cost_usd over the current calendar month across all warehouses."""
    month = time.strftime('%Y-%m', time.localtime(now or time.time()))
    total = 0.0
    for per_day in meters.list_meters().values():
        for day, entry in per_day.items():
            if day.startswith(f'{month}-'):
                total += float(entry.get('cost_usd', 0))
    return total


def kill_switch() -> bool:
    item = _table().get_item(Key=_KILL_SWITCH_KEY).get('Item')
    if not isinstance(item, dict):
        return False
    return bool(item.get('kill_switch', False))


def set_kill_switch(on: bool = True) -> None:
    _table().update_item(
        Key=_KILL_SWITCH_KEY,
        UpdateExpression='SET kill_switch = :v, updated_at = :t',
        ExpressionAttributeValues={':v': on, ':t': Decimal(str(time.time()))},
    )


def can_launch() -> bool:
    """False once the kill switch is on or the month hits the ceiling."""
    if kill_switch():
        return False
    return month_spend_usd() < SPARK_BUDGET_USD - SPARK_BUDGET_MARGIN_USD
