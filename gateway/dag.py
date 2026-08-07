"""Query-profile DAG fetching and parsing (Beacon #19).

Talks to the Spark driver UI REST API on port 4040 to fetch SQL execution
plans. After a query runs, the gateway looks up the execution by SQL text
(unique per query on a given driver) and fetches its full execution DAG.
"""

import json
import logging
import re
import time
import urllib.request

from config import SPARK_UI_PORT

log = logging.getLogger(__name__)

_DURATION_UNITS_MS = {'ms': 1.0, 's': 1000.0, 'm': 60_000.0, 'min': 60_000.0, 'h': 3_600_000.0}

_FETCH_TIMEOUT_S = 30.0
_POLL_INTERVAL_S = 0.25


def _ui_get(driver_ip: str, path: str, timeout: float = 2.0):
    url = f'http://{driver_ip}:{SPARK_UI_PORT}/api/v1{path}'
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def resolve_app_id(driver_ip: str) -> str | None:
    apps = _ui_get(driver_ip, '/applications')
    if not apps:
        return None
    running = [
        a for a in apps if any(not at.get('completed', True) for at in a.get('attempts', []))
    ]
    return (running or apps)[0]['id']


def metric_total(value: str) -> str:
    lines = value.strip().splitlines()
    if not lines:
        return ''
    return lines[-1].strip()


def parse_duration_ms(value: str) -> int | None:
    m = re.match(r'([\d,.]+)\s*(ms|min|s|m|h)\b', metric_total(value))
    if not m:
        return None
    num = float(m.group(1).replace(',', ''))
    return int(num * _DURATION_UNITS_MS.get(m.group(2), 1.0))


def is_nonzero_size(value: str) -> bool:
    m = re.match(r'([\d,.]+)', metric_total(value))
    return bool(m) and float(m.group(1).replace(',', '')) > 0


def transform_dag(detail: dict) -> dict:
    nodes = []
    shuffle_node_ids = set()
    for n in detail.get('nodes', []):
        metrics = {m['name']: m['value'] for m in n.get('metrics', [])}
        name = n.get('nodeName', '')

        is_shuffle = 'Exchange' in name or 'Shuffle' in name or 'shuffle bytes written' in metrics
        if is_shuffle:
            shuffle_node_ids.add(n['nodeId'])

        has_spill = 'spill size' in metrics and is_nonzero_size(metrics['spill size'])

        # Try every time-related metric Spark reports — WholeStageCodegen uses
        # 'duration', Scan has 'scan time', Exchange has 'shuffle write time' and
        # 'fetch wait time', aggregate has 'time in aggregation build'
        duration_ms = None
        for key in (
            'duration', 'scan time', 'shuffle write time',
            'fetch wait time', 'sort time', 'time in aggregation build',
            'time to broadcast',
        ):
            if key in metrics:
                duration_ms = parse_duration_ms(metrics[key])
                if duration_ms is not None:
                    break

        # Friendly labels for the UI when no duration is available (codegen
        # operators like Filter / Project / Range)
        summary_metric = None
        if 'number of output rows' in metrics:
            summary_metric = metric_total(metrics['number of output rows']) + ' rows'
        elif name.startswith('WholeStageCodegen') and duration_ms is not None:
            pass  # duration bar is sufficient
        elif 'scan time' in metrics:
            pass  # duration_ms already set above
        elif 'shuffle bytes written' in metrics:
            summary_metric = metric_total(metrics['shuffle bytes written']) + ' shuffled'

        nodes.append(
            {
                'id': n['nodeId'],
                'name': name,
                'duration_ms': duration_ms,
                'metrics': {k: metric_total(v) for k, v in metrics.items()},
                'is_shuffle': is_shuffle,
                'has_skew': False,
                'has_spill': has_spill,
                **({'summary_metric': summary_metric} if summary_metric else {}),
            }
        )

    edges = [
        {'from': e['fromId'], 'to': e['toId'], 'is_shuffle': e['fromId'] in shuffle_node_ids}
        for e in detail.get('edges', [])
    ]
    return {'nodes': nodes, 'edges': edges}


def fetch_query_dag_by_session(
    driver_ip: str, session_id: str, app_id: str | None = None
) -> dict | None:
    """Fetch the DAG for the latest SQL query of a Spark Connect session.

    Spark Connect executes don't support job descriptions client-side, so the
    SQL tab entry is matched by the session id embedded in its description,
    picking the most recently submitted COMPLETED execution. Queries run
    sequentially per warehouse, so "newest COMPLETED for this session" is the
    query we just fired. Polls up to _FETCH_TIMEOUT_S for completion.
    """
    try:
        app_id = app_id or resolve_app_id(driver_ip)
        if not app_id:
            return None

        needle = f'session_id: "{session_id}"'

        deadline = time.time() + _FETCH_TIMEOUT_S
        while time.time() < deadline:
            execs = _ui_get(driver_ip, f'/applications/{app_id}/sql?details=false')
            match = None
            for e in execs:
                if needle in e.get('description', '') and e.get('status') == 'COMPLETED':
                    if match is None or e.get('submissionTime', '') > match.get('submissionTime', ''):
                        match = e
            if match:
                detail = _ui_get(
                    driver_ip, f'/applications/{app_id}/sql/{match["id"]}?details=true'
                )
                if detail.get('nodes'):
                    return transform_dag(detail)
                return None

            time.sleep(_POLL_INTERVAL_S)

        log.warning('DAG fetch timed out for session %s', session_id)

    except Exception as exc:
        log.warning('Query DAG fetch failed for driver %s: %s', driver_ip, exc)

    return None
