"""Cost Center data access — AWS resource inventory + billing series.

Every function is a thin boto3 wrapper so local_dev.py can swap in synthetic
implementations without touching the routes. Production data comes from:

- resourcegroupstaggingapi (tagged-resource inventory, Project=flashpoint)
- ECS list/describe tasks (live drivers + executors)
- EC2 describe instances/volumes (the always-on gateway + its root EBS)
- Cost Explorer GetCostAndUsage (authoritative daily totals, ~24h lag)
"""

import datetime

import boto3

from config import CLUSTER, REGION

PROJECT_TAG = 'flashpoint'

_taggings = boto3.client('resourcegroupstaggingapi', region_name=REGION)
_ecs = boto3.client('ecs', region_name=REGION)
_ec2 = boto3.client('ec2', region_name=REGION)
_ce = boto3.client('ce', region_name=REGION)

# Static on-demand hourly rates (USD) for the gateway EC2 + EBS — enough for
# honest monthly estimates without the Pricing API (which we already can call
# later; the gateway role has pricing:GetProducts).
_INSTANCE_RATE = {'t4g.small': 0.0168}
_EBS_GB_MO = 0.08  # gp3


def list_tagged_resources() -> list[dict]:
    """All resources carrying the Project tag, as {arn, tags}."""
    out: list[dict] = []
    paginator = _taggings.get_paginator('get_resources')
    for page in paginator.paginate(TagFilters=[{'Key': 'Project', 'Values': [PROJECT_TAG]}]):
        for r in page.get('ResourceTagMappingList', []):
            out.append({'arn': r['ResourceARN'], 'tags': {t['Key']: t['Value'] for t in r.get('Tags', [])}})
    return out


def list_running_tasks() -> list[dict]:
    """Running Fargate tasks in the cluster, with role/start time."""
    arns = _ecs.list_tasks(cluster=CLUSTER, desiredStatus='RUNNING').get('taskArns', [])
    if not arns:
        return []
    tasks = _ecs.describe_tasks(cluster=CLUSTER, tasks=arns).get('tasks', [])
    out = []
    for t in tasks:
        role = None
        if t.get('containers'):
            role = t['containers'][0]['name']  # spark-connect (driver) | spark-executor
        out.append({
            'arn': t['taskArn'],
            'role': role,
            'capacity': t.get('capacityProviderName'),
            'started_at': t.get('startedAt'),
            'cpu': t.get('cpu'),
            'memory': t.get('memory'),
        })
    return out


def list_instances() -> list[dict]:
    resp = _ec2.describe_instances(
        Filters=[{'Name': 'tag:Project', 'Values': [PROJECT_TAG]}]
    )
    out = []
    for r in resp.get('Reservations', []):
        for i in r.get('Instances', []):
            out.append({
                'id': i['InstanceId'],
                'type': i['InstanceType'],
                'state': i['State']['Name'],
                'launch_time': i.get('LaunchTime'),
                'tags': {t['Key']: t['Value'] for t in i.get('Tags', [])},
            })
    return out


def list_volumes() -> list[dict]:
    resp = _ec2.describe_volumes(
        Filters=[{'Name': 'tag:Project', 'Values': [PROJECT_TAG]}]
    )
    return [
        {
            'id': v['VolumeId'],
            'state': v['State'],
            'size_gb': v['Size'],
            'type': v['VolumeType'],
        }
        for v in resp.get('Volumes', [])
    ]


def get_daily_cost(days: int) -> list[dict] | None:
    """Daily cost series from Cost Explorer, or None when unavailable.

    Filtered by the Project tag; requires the tag to be activated as a cost
    allocation tag in Billing. Returns [{date, total_usd}, ...] ascending.
    """
    today = datetime.date.today()
    try:
        resp = _ce.get_cost_and_usage(
            TimePeriod={
                'Start': (today - datetime.timedelta(days=days)).strftime('%Y-%m-%d'),
                'End': (today + datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
            },
            Granularity='DAILY',
            Metrics=['UnblendedCost'],
            Filter={'Tags': {'Key': 'Project', 'Values': [PROJECT_TAG]}},
        )
    except Exception:
        return None
    out = []
    for day in resp.get('ResultsByTime', []):
        date = day.get('TimePeriod', {}).get('Start')
        amount = float(day['Total']['UnblendedCost']['Amount'])
        if date:
            out.append({'date': date, 'total_usd': round(amount, 4)})
    return out or None


def monthly_estimate(kind: str, **meta) -> float | None:
    """Rough monthly USD estimate for a resource row; None when unknowable."""
    if kind == 'ec2':
        rate = _INSTANCE_RATE.get(meta.get('type', ''))
        return round(rate * 730, 2) if rate else None
    if kind == 'ebs':
        return round((meta.get('size_gb', 0) or 0) * _EBS_GB_MO, 2)
    return None
