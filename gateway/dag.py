"""Query-profile DAG fetching and parsing (Beacon #19).

Talks to the Spark driver UI REST API on port 4040 to fetch SQL execution
plans and transform them into a compact DAG for the frontend.
"""

import json
import logging
import re
import time
import urllib.request

from config import SPARK_UI_PORT

log = logging.getLogger(__name__)

_DURATION_UNITS_MS = {'ms': 1.0, 's': 1000.0, 'm': 60_000.0, 'min': 60_000.0, 'h': 3_600_000.0}


def _ui_get(driver_ip: str, path: str, timeout: float = 2.0):
    """GET http://{driver_ip}:{SPARK_UI_PORT}/api/v1{path} and parse JSON."""
    url = f'http://{driver_ip}:{SPARK_UI_PORT}/api/v1{path}'
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def resolve_app_id(driver_ip: str) -> str | None:
    """Return the running application's id (SparkConnectServer hosts exactly one)."""
    apps = _ui_get(driver_ip, '/applications')
    if not apps:
        return None
    running = [
        a for a in apps if any(not at.get('completed', True) for at in a.get('attempts', []))
    ]
    return (running or apps)[0]['id']


def metric_total(value: str) -> str:
    """Return the human-readable total from a multiline Spark metric string."""
    lines = value.strip().splitlines()
    if not lines:
        return ''
    return lines[-1].strip()


def parse_duration_ms(value: str) -> int | None:
    """Parse a Spark duration metric like '390 ms' into milliseconds."""
    m = re.match(r'([\d,.]+)\s*(ms|min|s|m|h)\b', metric_total(value))
    if not m:
        return None
    num = float(m.group(1).replace(',', ''))
    return int(num * _DURATION_UNITS_MS.get(m.group(2), 1.0))


def is_nonzero_size(value: str) -> bool:
    """True if a Spark size metric like '512.0 KiB' is greater than zero."""
    m = re.match(r'([\d,.]+)', metric_total(value))
    return bool(m) and float(m.group(1).replace(',', '')) > 0


def transform_dag(detail: dict) -> dict:
    """Map a raw Spark SQL execution detail into the compact UI schema."""
    nodes = []
    shuffle_node_ids = set()
    for n in detail.get('nodes', []):
        metrics = {m['name']: m['value'] for m in n.get('metrics', [])}
        name = n.get('nodeName', '')

        is_shuffle = 'Exchange' in name or 'Shuffle' in name or 'shuffle bytes written' in metrics
        if is_shuffle:
            shuffle_node_ids.add(n['nodeId'])

        has_spill = 'spill size' in metrics and is_nonzero_size(metrics['spill size'])

        duration_ms = None
        for key in ('duration', 'sort time', 'time in aggregation build'):
            if key in metrics:
                duration_ms = parse_duration_ms(metrics[key])
                if duration_ms is not None:
                    break

        nodes.append(
            {
                'id': n['nodeId'],
                'name': name,
                'duration_ms': duration_ms,
                'metrics': {k: metric_total(v) for k, v in metrics.items()},
                'is_shuffle': is_shuffle,
                'has_skew': False,
                'has_spill': has_spill,
            }
        )

    edges = [
        {'from': e['fromId'], 'to': e['toId'], 'is_shuffle': e['fromId'] in shuffle_node_ids}
        for e in detail.get('edges', [])
    ]
    return {'nodes': nodes, 'edges': edges}


def fetch_query_dag(warehouse: dict, before_ids: set[int]) -> dict | None:
    """Best-effort: fetch the just-run query's execution DAG from the driver UI."""
    driver_ip = warehouse['task_ip']
    try:
        app_id = warehouse.get('app_id') or resolve_app_id(driver_ip)
        if not app_id:
            return None
        warehouse['app_id'] = app_id

        deadline = time.time() + 1.5
        while time.time() < deadline:
            execs = _ui_get(driver_ip, f'/applications/{app_id}/sql?details=false')
            new = [e for e in execs if e['id'] not in before_ids and e.get('status') == 'COMPLETED']
            if new:
                exec_id = max(e['id'] for e in new)
                detail = _ui_get(driver_ip, f'/applications/{app_id}/sql/{exec_id}?details=true')
                if detail.get('nodes'):
                    return transform_dag(detail)
            time.sleep(0.15)
    except Exception as exc:
        log.warning('Query DAG fetch failed for driver %s: %s', driver_ip, exc)
    return None


def sql_execution_ids(warehouse: dict) -> set[int]:
    """Best-effort snapshot of existing SQL execution ids before a query runs."""
    try:
        app_id = warehouse.get('app_id') or resolve_app_id(warehouse['task_ip'])
        if not app_id:
            return set()
        warehouse['app_id'] = app_id
        execs = _ui_get(warehouse['task_ip'], f'/applications/{app_id}/sql?details=false')
        return {e['id'] for e in execs}
    except Exception:
        return set()
