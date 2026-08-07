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


_TASK_TIME_RE = re.compile(
    r'([\d,.]+)\s*(ms|min|s|m|h)\b\s*\(\s*([\d,.]+)\s*ms\s*,\s*([\d,.]+)\s*ms\s*,\s*([\d,.]+)\s*ms'
)


def parse_task_breakdown(value: str) -> dict | None:
    """Extract total, median, and estimated task count from Spark's
    'total (min, med, max (stageId: taskId))\\nN ms (...)' format."""
    stripped = value.strip().replace('\n', ' ')
    m = _TASK_TIME_RE.search(stripped)
    if not m:
        return None
    total_s = float(m.group(1).replace(',', ''))
    total_ms = int(total_s * _DURATION_UNITS_MS.get(m.group(2), 1.0))
    med_ms = float(m.group(4).replace(',', ''))
    task_count = None
    if med_ms > 0 and total_ms > 0:
        task_count = max(1, round(total_ms / med_ms))
    return {'total_ms': total_ms, 'median_task_ms': int(med_ms), 'task_count': task_count}


def is_nonzero_size(value: str) -> bool:
    m = re.match(r'([\d,.]+)', metric_total(value))
    return bool(m) and float(m.group(1).replace(',', '')) > 0


# ---- column treatments (Snowflake-style) ----

_BLOCK_RE = re.compile(r'^\((\d+)\)\s+([^\n]+)\n(.*?)(?=^\(\d+\)\s|\Z)', re.MULTILINE | re.DOTALL)
_CODEGEN_ID_RE = re.compile(r'codegen id\s*:\s*(\d+)')
_STAGE_NAME_RE = re.compile(r'(QueryStage|^Reused|^InputAdapter)')
_TRAIL_SPACE_RE = re.compile(r'\s+')
# Operators Spark never puts inside a codegen stage — their nodes must not be
# mistaken for stage members when splitting the cluster's member run.
_MEMBER_SKIP_RE = re.compile(r'(Scan|Exchange|ShuffleRead|InputAdapter|AdaptiveSparkPlan)')


def _block_entries(body: str) -> list[list[str]]:
    """Key/value lines from a plan block, e.g. 'Output [1]: [customer_id#2]'."""
    entries = []
    for line in body.strip().splitlines():
        line = line.strip()
        if not line or line.startswith('Batched:'):
            continue
        key, _, value = line.partition(':')
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        # strip Spark attribute ids (#2L) — noise for the user
        value = re.sub(r'#\d+[A-Z]?', '', value)
        entries.append([key, value])
    return entries


def _parse_blocks(plan_description: str) -> dict[int, dict]:
    """Parse '(<n>) Operator ...' blocks into {number: {...}}."""
    blocks = {}
    for num_s, header, body in _BLOCK_RE.findall(plan_description):
        codegen = _CODEGEN_ID_RE.search(header)
        name = header.split('[', 1)[0].strip()
        blocks[int(num_s)] = {
            'name': name,
            'codegen_id': int(codegen.group(1)) if codegen else None,
            'entries': _block_entries(body),
        }
    return blocks


def _final_plan_numbers(plan_description: str) -> set[int]:
    """Block numbers that belong to the executed (Final) plan, from the tree.

    AQE plans print both a Final and an Initial Plan; only the Final one is
    graphed, so the Initial Plan's blocks must be excluded."""
    numbers = set()
    in_tree = False
    section = None
    for line in plan_description.splitlines():
        if line.startswith('== Physical Plan =='):
            in_tree = True
            continue
        if not in_tree:
            continue
        m = re.search(r'==\s*([A-Za-z ]+?)\s*==', line)  # '== Final Plan ==' etc.
        if m:
            section = m.group(1).strip()
            continue
        if re.match(r'^\(\d+\)\s', line):
            break  # block listing starts — tree is done
        if section == 'Initial Plan':
            continue
        m = re.search(r'\((\d+)\)', line)
        if m:
            numbers.add(int(m.group(1)))
    return numbers


def parse_column_treatments(plan_description: str, nodes: list[dict]) -> dict[int, list[dict]]:
    """Attach each operator's column treatment (Output/Keys/Condition/...) to
    the graph node it belongs to, keyed by nodeId.

    Blocks tagged '[codegen id : N]' belong to the operators inside the
    WholeStageCodegen (N) stage: each block lands on its own member node (the
    contiguous run of plain nodes just before the cluster in execution order,
    minus operators Spark never codegen's), so a HashAggregate node shows its
    own Keys/Functions instead of burying them on the cluster. Untagged blocks
    map to plain nodes by operator name, in plan order. Query-stage and
    Initial-Plan blocks have no node."""
    if not plan_description:
        return {}
    blocks = _parse_blocks(plan_description)
    if not blocks:
        return {}
    final_numbers = _final_plan_numbers(plan_description)

    # The node array is in execution order: data source first, final operator
    # last, with each WholeStageCodegen cluster immediately after its members.
    clusters: dict[int, int] = {}
    for i, n in enumerate(nodes):
        m = re.match(r'^WholeStageCodegen\s*\((\d+)\)', n.get('nodeName', ''))
        if m:
            clusters[int(m.group(1))] = i
    cluster_indexes = sorted(clusters.values())

    claimed: set[int] = set()
    treatments: dict[int, list[dict]] = {}

    def attach(node_id: int, block: dict) -> None:
        treatments.setdefault(node_id, []).append(
            {'operator': block['name'], 'entries': block['entries']}
        )

    def member_node_id(codegen_id: int, name: str) -> int | None:
        """First unclaimed member of the stage whose name matches, in execution order."""
        pos = clusters.get(codegen_id)
        if pos is None:
            return None
        start = 0
        for other in cluster_indexes:
            if other < pos:
                start = other + 1
        for idx in range(start, pos):
            node = nodes[idx]
            nid = node['nodeId']
            if nid in claimed or _MEMBER_SKIP_RE.search(node.get('nodeName', '')):
                continue
            if _TRAIL_SPACE_RE.sub(' ', node.get('nodeName', '')) == name.split(' ')[0]:
                return nid
        return None

    def match_plain(name: str) -> int | None:
        """First unclaimed plain node whose name matches, in plan order."""
        for nid in plain_nodes:
            if nid in claimed:
                continue
            node = next((n for n in nodes if n['nodeId'] == nid), None)
            if node and _TRAIL_SPACE_RE.sub(' ', node.get('nodeName', '')) == name:
                return nid
        return None

    plain_nodes = [
        n['nodeId']
        for n in sorted(nodes, key=lambda n: n['nodeId'])
        if not re.match(r'^WholeStageCodegen\s*\((\d+)\)', n.get('nodeName', ''))
    ]

    # Codegen blocks first, so member nodes are claimed before plain matching
    # gets a chance to steal them.
    for num in sorted(blocks):
        block = blocks[num]
        if num not in final_numbers or not block['entries']:
            continue
        if _STAGE_NAME_RE.search(block['name']):
            continue
        if block['codegen_id'] is None:
            continue
        node_id = member_node_id(block['codegen_id'], block['name'])
        if node_id is None:
            pos = clusters.get(block['codegen_id'])
            if pos is not None:  # unrecognized operator → keep it on the cluster
                attach(nodes[pos]['nodeId'], block)
            continue
        claimed.add(node_id)
        attach(node_id, block)

    for num in sorted(blocks):
        block = blocks[num]
        if num not in final_numbers or not block['entries']:
            continue
        if _STAGE_NAME_RE.search(block['name']) or block['codegen_id'] is not None:
            continue
        node_id = match_plain(block['name'])
        if node_id is not None:
            claimed.add(node_id)
            attach(node_id, block)

    return treatments


def transform_dag(detail: dict) -> dict:
    nodes = []
    shuffle_node_ids = set()
    treatments = parse_column_treatments(detail.get('planDescription', ''), detail.get('nodes', []))
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
        median_task_ms = None
        task_count = None
        for key in (
            'duration',
            'scan time',
            'shuffle write time',
            'fetch wait time',
            'sort time',
            'time in aggregation build',
            'time to broadcast',
        ):
            if key in metrics:
                breakdown = parse_task_breakdown(metrics[key])
                if breakdown:
                    duration_ms = breakdown['total_ms']
                    median_task_ms = breakdown['median_task_ms']
                    task_count = breakdown['task_count']
                else:
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
                'median_task_ms': median_task_ms,
                'task_count': task_count,
                'metrics': {k: metric_total(v) for k, v in metrics.items()},
                'is_shuffle': is_shuffle,
                'has_skew': False,
                'has_spill': has_spill,
                **({'summary_metric': summary_metric} if summary_metric else {}),
                **(
                    {'treatments': treatments.get(n['nodeId'], [])}
                    if treatments.get(n['nodeId'])
                    else {}
                ),
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
                    if match is None or e.get('submissionTime', '') > match.get(
                        'submissionTime', ''
                    ):
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
