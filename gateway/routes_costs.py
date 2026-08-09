"""Cost Center routes — tagged resource inventory + cost series.

GET /resources — every Flashpoint AWS resource with state + monthly estimate,
joined to warehouse records so Fargate tasks say which warehouse they serve.
GET /costs    — daily spend series (Cost Explorer, tag-filtered) + meter-based
                per-warehouse cost (live) + period totals.
"""

import logging
import time
from datetime import date, timedelta

from fastapi import APIRouter

import cost_data
import meters
import store
from config import MONTHLY_BUDGET_USD, REGION

log = logging.getLogger(__name__)
router = APIRouter(tags=['costs'])


@router.get('/resources')
def list_resources():
    warehouses = {w['name']: w for w in store.list_warehouses()}
    by_arn = {}
    for wh in warehouses.values():
        if wh.get('task_arn'):
            by_arn[wh['task_arn']] = wh
        for arn in wh.get('executor_arns') or []:
            by_arn[arn] = wh

    rows: list[dict] = []
    now = time.time()

    # Running Fargate tasks — join to their warehouse by task ARN.
    for t in cost_data.list_running_tasks():
        wh = by_arn.get(t['arn'])
        is_driver = (t.get('role') or '') == 'spark-connect'
        uptime_h = None
        if t.get('started_at'):
            uptime_h = round(max(0, now - t['started_at'].timestamp()) / 3600, 2)
        rows.append({
            'id': t['arn'],
            'kind': 'fargate',
            'role': 'driver' if is_driver else 'executor',
            'warehouse': wh['name'] if wh else None,
            'state': 'running',
            'type': f"{(t.get('cpu') or '?')} vCPU / {(t.get('memory') or '?')} MB",
            'uptime_h': uptime_h,
            'monthly_est': None,  # included in the warehouse's rate
            'console_url': _console_url(t['arn'], 'fargate'),
        })

    # Gateway EC2 instance + its root EBS volume (the always-on cost).
    instances = {i['id']: i for i in cost_data.list_instances()}
    for i in instances.values():
        rows.append({
            'id': i['id'],
            'kind': 'ec2',
            'role': 'gateway',
            'warehouse': None,
            'state': i['state'],
            'type': i['type'],
            'uptime_h': None,
            'monthly_est': cost_data.monthly_estimate('ec2', type=i['type']),
            'console_url': _console_url(i['id'], 'ec2'),
        })
    for v in cost_data.list_volumes():
        rows.append({
            'id': v['id'],
            'kind': 'ebs',
            'role': 'gateway-root',
            'warehouse': None,
            'state': v['state'],
            'type': f"{v['type']} {v['size_gb']} GB",
            'uptime_h': None,
            'monthly_est': cost_data.monthly_estimate('ebs', size_gb=v['size_gb']),
            'console_url': _console_url(v['id'], 'ebs'),
        })

    # Everything else with the Project tag — DynamoDB, S3, ECR, log groups, VPC…
    for r in cost_data.list_tagged_resources():
        arn = r['arn']
        if ':task/' in arn or ':instance/' in arn or ':volume/' in arn:
            continue  # already covered above
        kind = 'dynamodb' if ':dynamodb:' in arn else 's3' if ':s3:' in arn else 'ecr' if ':ecr:' in arn else 'logs' if ':logs:' in arn else 'vpc' if ':vpc/' in arn else 'other'
        rows.append({
            'id': arn,
            'kind': kind,
            'role': 'infra',
            'warehouse': None,
            'state': 'active',
            'type': kind,
            'uptime_h': None,
            'monthly_est': None,
            'console_url': _console_url(arn, kind),
        })

    rows.sort(key=lambda r: (r['kind'], r['role'], r['id']))
    return {'resources': rows, 'count': len(rows)}


@router.get('/costs')
def get_costs(days: int = 30):
    days = max(7, min(days, 90))

    # Daily series: Cost Explorer when available, otherwise meter-derived.
    ce_series = cost_data.get_daily_cost(days)
    meter_map = meters.list_meters(days)
    meter_series = _meter_daily_series(meter_map, days)

    if ce_series:
        daily = _merge_series(ce_series, meter_series)
        source = 'cost-explorer'
    else:
        daily = meter_series
        source = 'meters'

    today = date.today().isoformat()
    totals = {
        'today': round(sum(d['total_usd'] for d in daily if d['date'] == today), 4),
        'd7': round(sum(d['total_usd'] for d in daily[-7:]), 4),
        'd30': round(sum(d['total_usd'] for d in daily), 4),
    }
    per_warehouse = []
    for wh in store.list_warehouses():
        name = wh['name']
        series = [_series_total(meter_map.get(name, {}), days)]
        per_warehouse.append({
            'name': name,
            'status': wh.get('status'),
            'size': wh.get('size'),
            'today': series[0][0],
            'd7': series[0][1],
            'd30': series[0][2],
        })
    per_warehouse.sort(key=lambda w: -w['d30'])

    return {
        'days': daily,
        'totals': totals,
        'per_warehouse': per_warehouse,
        'projection': _projection(daily),
        'source': source,
    }


def _projection(daily: list[dict]) -> dict:
    """7-day average scaled to the calendar month, budget flag, spike days.

    Spike days (daily spend > 1.5x the window average) are flagged so the
    chart can highlight them — the first sign of a runaway query.
    """
    empty = {
        'monthly_usd': 0.0,
        'daily_avg7': 0.0,
        'budget_usd': MONTHLY_BUDGET_USD,
        'over_budget': False,
        'spike_days': [],
    }
    if not daily:
        return empty

    recent = [d['total_usd'] for d in daily[-7:]]
    avg7 = sum(recent) / len(recent)
    month = date.today()
    next_month = month.replace(day=28) + timedelta(days=4)  # safe month rollover
    days_in_month = (next_month.replace(day=1) - month.replace(day=1)).days
    monthly = round(avg7 * days_in_month, 2)

    avg_all = sum(d['total_usd'] for d in daily) / len(daily)
    threshold = 1.5 * avg_all
    spike_days = [d['date'] for d in daily if d['total_usd'] > threshold]

    return {
        'monthly_usd': monthly,
        'daily_avg7': round(avg7, 4),
        'budget_usd': MONTHLY_BUDGET_USD,
        'over_budget': monthly > MONTHLY_BUDGET_USD,
        'spike_days': spike_days,
    }


def _console_url(arn_or_id: str, kind: str) -> str | None:
    """AWS Console deep link for a resource row; None when unlinkable."""
    if kind == 'fargate':
        parts = arn_or_id.split('/')  # arn:aws:ecs:region:acct:task/cluster/taskid
        if len(parts) != 3 or ':task' not in parts[0]:
            return None
        cluster, task_id = parts[1], parts[2]
        return (
            f'https://{REGION}.console.aws.amazon.com/ecs/home?region={REGION}'
            f'#/clusters/{cluster}/tasks/{task_id}/details'
        )
    if kind == 'ec2':
        if not arn_or_id.startswith('i-'):
            return None
        return f'https://{REGION}.console.aws.amazon.com/ec2/home?region={REGION}#InstanceDetails:instanceId={arn_or_id}'
    if kind == 'ebs':
        if not arn_or_id.startswith('vol-'):
            return None
        return f'https://{REGION}.console.aws.amazon.com/ec2/home?region={REGION}#VolumeDetails:volumeId={arn_or_id}'
    if kind == 'dynamodb':
        if ':dynamodb:' not in arn_or_id:
            return None
        table = arn_or_id.split('/')[-1]
        return f'https://{REGION}.console.aws.amazon.com/dynamodbv2/home?region={REGION}#table/{table}'
    if kind == 's3':
        bucket = arn_or_id.split(':')[-1]
        return f'https://s3.console.aws.amazon.com/s3/buckets/{bucket}?region={REGION}'
    if kind == 'ecr':
        return f'https://{REGION}.console.aws.amazon.com/ecr/repositories?region={REGION}'
    if kind == 'logs':
        return f'https://{REGION}.console.aws.amazon.com/cloudwatch/home?region={REGION}#logsV2:log-groups'
    if kind == 'vpc':
        vpc_id = arn_or_id.split('/')[-1]
        if not vpc_id.startswith('vpc-'):
            return None
        return f'https://{REGION}.console.aws.amazon.com/vpc/home?region={REGION}#VpcDetails:vpcId={vpc_id}'
    return None


def _meter_daily_series(meter_map: dict, days: int) -> list[dict]:
    """Per-day totals from the meters table, one entry per day present."""
    out: dict[str, float] = {}
    for wh_days in meter_map.values():
        for day, m in wh_days.items():
            out[day] = out.get(day, 0) + m['cost_usd']
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [{'date': d, 'total_usd': round(v, 4)} for d, v in sorted(out.items()) if d >= cutoff]


def _merge_series(ce: list[dict], meters_series: list[dict]) -> list[dict]:
    """CE is authoritative; meters fill days CE hasn't reported yet (today)."""
    by_date = {d['date']: d['total_usd'] for d in ce}
    for m in meters_series:
        if m['date'] not in by_date:
            by_date[m['date']] = m['total_usd']
    return [{'date': d, 'total_usd': round(v, 4)} for d, v in sorted(by_date.items())]


def _series_total(days_map: dict, days: int) -> tuple[float, float, float]:
    """(today, d7, d30) totals for one warehouse's day map."""
    today = date.today().isoformat()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    t7 = (date.today() - timedelta(days=7)).isoformat()
    today_v = d7 = d30 = 0.0
    for day, m in days_map.items():
        if day < cutoff:
            continue
        d30 += m['cost_usd']
        if day >= t7:
            d7 += m['cost_usd']
        if day == today:
            today_v = m['cost_usd']
    return round(today_v, 4), round(d7, 4), round(d30, 4)
