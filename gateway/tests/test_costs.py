"""Cost Center tests — meter accrual + /resources + /costs endpoints.

All boto3 clients are MagicMocks (see conftest), so cost_data and meters are
swapped for in-memory/synthetic versions before exercising the routes.
"""

import time
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

import cost_data
import meters
import store
from config import HOURLY_RATE

_ORIG_ACCRUE = meters.accrue  # captured before fixtures swap it out

_METER_DB: dict[tuple[str, str], dict] = {}


def _accrue(name: str, seconds: float, cost_usd: float) -> None:
    key = (name, meters.day_key())
    row = _METER_DB.setdefault(key, {'compute_seconds': 0.0, 'cost_usd': 0.0})
    row['compute_seconds'] += seconds
    row['cost_usd'] += cost_usd


def _list_meters(days: int = 30) -> dict:
    out: dict = {}
    for (name, day), row in _METER_DB.items():
        out.setdefault(name, {})[day] = dict(row)
    return out


@pytest.fixture(autouse=True)
def mock_meters(monkeypatch):
    _METER_DB.clear()
    monkeypatch.setattr(meters, 'accrue', _accrue)
    monkeypatch.setattr(meters, 'list_meters', _list_meters)


@pytest.fixture(autouse=True)
def mock_cost_data(monkeypatch):
    monkeypatch.setattr(cost_data, 'list_running_tasks', lambda: [])
    monkeypatch.setattr(cost_data, 'list_instances', lambda: [])
    monkeypatch.setattr(cost_data, 'list_volumes', lambda: [])
    monkeypatch.setattr(cost_data, 'list_tagged_resources', lambda: [])
    monkeypatch.setattr(cost_data, 'get_daily_cost', lambda days: None)


def _seed_warehouse(name: str, status: str = 'running', task_arn: str = '',
                    executor_arns: list | None = None, size: str = 'XS'):
    store.put_warehouse(name, {
        'task_arn': task_arn,
        'executor_arns': executor_arns or [],
        'status': status,
        'size': size,
        'executor_count': len(executor_arns or []),
    })


class TestAccrueSession:
    def test_bills_delta_since_checkpoint(self):
        now = time.time()
        rec = {'name': 'wh1', 'size': 'S', 'session_started_at': now - 180, 'last_metered_at': now - 180}
        seconds = meters.accrue_session(rec, now=now)
        assert seconds == 180
        row = _METER_DB[('wh1', meters.day_key())]
        assert row['compute_seconds'] == 180
        assert row['cost_usd'] == pytest.approx(180 / 3600 * HOURLY_RATE['S'])

    def test_no_double_count_when_checkpoint_advances(self):
        # The caller (reconcile/reaper, suspend/delete routes) advances
        # last_metered_at after each accrue — only the delta is billed.
        now = time.time()
        rec = {'name': 'wh1', 'size': 'XS', 'session_started_at': now - 300, 'last_metered_at': now - 300}
        assert meters.accrue_session(rec, now=now) == 300
        rec['last_metered_at'] = now
        assert meters.accrue_session(rec, now=now + 60) == 60
        assert _METER_DB[('wh1', meters.day_key())]['compute_seconds'] == 360

    def test_no_checkpoint_bills_nothing(self):
        assert meters.accrue_session({'name': 'wh1', 'size': 'XS'}, now=time.time()) == 0

    def test_unknown_size_falls_back_to_xs(self):
        now = time.time()
        rec = {'name': 'wh1', 'size': 'ZZZ', 'session_started_at': now - 100, 'last_metered_at': now - 100}
        meters.accrue_session(rec, now=now)
        assert _METER_DB[('wh1', meters.day_key())]['cost_usd'] == pytest.approx(100 / 3600 * HOURLY_RATE['XS'])


class TestAccrueWritesAtomicAdd:
    def test_update_expression(self, monkeypatch):
        table = MagicMock()
        monkeypatch.setattr(meters, '_dynamodb', MagicMock(Table=lambda name: table))
        monkeypatch.setattr(meters, 'accrue', _ORIG_ACCRUE)
        meters.accrue('wh1', 120.5, 0.01)
        kwargs = table.update_item.call_args.kwargs
        assert kwargs['Key'] == {'pk': 'wh:wh1', 'sk': f'day:{meters.day_key()}'}
        assert kwargs['UpdateExpression'] == 'ADD compute_seconds :s, cost_usd :c'


class TestCostsEndpoint:
    def test_meter_source_with_no_ce(self, client, mock_store):
        _seed_warehouse('demo')
        now = time.time()
        meters.accrue_session({'name': 'demo', 'size': 'S', 'session_started_at': now - 3600, 'last_metered_at': now - 3600}, now=now)

        resp = client.get('/costs?days=30')
        assert resp.status_code == 200
        data = resp.json()
        assert data['source'] == 'meters'
        assert data['totals']['today'] == pytest.approx(3600 / 3600 * HOURLY_RATE['S'], rel=1e-6)
        assert data['per_warehouse'][0]['name'] == 'demo'
        assert data['per_warehouse'][0]['today'] == pytest.approx(HOURLY_RATE['S'], rel=1e-6)

    def test_cost_explorer_source_is_authoritative(self, client, mock_store, monkeypatch):
        today = date.today()

        def fake_daily(days):
            return [
                {'date': (today - timedelta(days=i)).isoformat(), 'total_usd': 1.0}
                for i in range(days)
            ]

        monkeypatch.setattr(cost_data, 'get_daily_cost', fake_daily)
        resp = client.get('/costs?days=30')
        data = resp.json()
        assert data['source'] == 'cost-explorer'
        assert data['totals']['today'] == 1.0
        assert data['totals']['d7'] == 7.0
        assert data['totals']['d30'] == 30.0
        assert len(data['days']) == 30

    def test_days_clamped(self, client):
        assert client.get('/costs?days=1').json()['source'] in ('meters', 'cost-explorer')
        assert client.get('/costs?days=200').status_code == 200


class TestProjection:
    def test_flat_series_projects_monthly(self, client, mock_store, monkeypatch):
        today = date.today()

        def fake_daily(days):
            return [
                {'date': (today - timedelta(days=i)).isoformat(), 'total_usd': 0.5}
                for i in range(days)
            ]

        monkeypatch.setattr(cost_data, 'get_daily_cost', fake_daily)
        data = client.get('/costs?days=30').json()['projection']
        month = date.today()
        next_month = month.replace(day=28) + timedelta(days=4)
        days_in_month = (next_month.replace(day=1) - month.replace(day=1)).days
        assert data['daily_avg7'] == 0.5
        assert data['monthly_usd'] == pytest.approx(0.5 * days_in_month, rel=1e-6)
        assert data['over_budget'] is False
        assert data['spike_days'] == []

    def test_over_budget_flagged(self, client, mock_store, monkeypatch):
        today = date.today()

        def fake_daily(days):
            return [
                {'date': (today - timedelta(days=i)).isoformat(), 'total_usd': 5.0}
                for i in range(days)
            ]

        monkeypatch.setattr(cost_data, 'get_daily_cost', fake_daily)
        data = client.get('/costs?days=30').json()['projection']
        assert data['over_budget'] is True
        assert data['monthly_usd'] > data['budget_usd']

    def test_spike_days_detected(self, client, mock_store, monkeypatch):
        today = date.today()

        def fake_daily(days):
            out = []
            for i in range(days):
                total = 1.0 if i % 10 != 0 else 10.0  # one spike every 10 days
                out.append({'date': (today - timedelta(days=i)).isoformat(), 'total_usd': total})
            return out

        monkeypatch.setattr(cost_data, 'get_daily_cost', fake_daily)
        data = client.get('/costs?days=30').json()['projection']
        assert len(data['spike_days']) >= 3  # avg ~1.9, spike 10 > 1.5x avg

    def test_empty_series_is_safe(self, client, mock_store):
        data = client.get('/costs?days=30').json()['projection']
        assert data['monthly_usd'] == 0.0
        assert data['over_budget'] is False
        assert data['spike_days'] == []


class TestResourcesEndpoint:
    def test_fargate_rows_join_warehouse(self, client, mock_store, monkeypatch):
        started = datetime.now() - timedelta(hours=2)
        monkeypatch.setattr(cost_data, 'list_running_tasks', lambda: [{
            'arn': 'arn:driver',
            'role': 'spark-connect',
            'started_at': started,
            'cpu': '2048',
            'memory': '8192',
        }])
        _seed_warehouse('my-wh', task_arn='arn:driver')

        resp = client.get('/resources')
        assert resp.status_code == 200
        rows = resp.json()['resources']
        driver = [r for r in rows if r['kind'] == 'fargate'][0]
        assert driver['warehouse'] == 'my-wh'
        assert driver['role'] == 'driver'
        assert driver['uptime_h'] == pytest.approx(2.0, abs=0.01)

    def test_gateway_ec2_and_ebs_estimated(self, client, mock_store, monkeypatch):
        monkeypatch.setattr(cost_data, 'list_instances', lambda: [{
            'id': 'i-1', 'type': 't4g.small', 'state': 'running',
            'launch_time': datetime.now() - timedelta(days=10),
        }])
        monkeypatch.setattr(cost_data, 'list_volumes', lambda: [{
            'id': 'vol-1', 'state': 'in-use', 'size_gb': 20, 'type': 'gp3',
        }])
        rows = client.get('/resources').json()['resources']
        ec2 = [r for r in rows if r['kind'] == 'ec2'][0]
        assert ec2['monthly_est'] == pytest.approx(round(0.0168 * 730, 2), rel=1e-6)
        assert ec2['role'] == 'gateway'
        ebs = [r for r in rows if r['kind'] == 'ebs'][0]
        assert ebs['monthly_est'] == pytest.approx(20 * 0.08, rel=1e-6)

    def test_tagged_infra_rows(self, client, mock_store, monkeypatch):
        monkeypatch.setattr(cost_data, 'list_tagged_resources', lambda: [
            {'arn': 'arn:aws:dynamodb:us-east-1:0:table/wh', 'tags': {'Project': 'flashpoint'}},
            {'arn': 'arn:aws:logs:us-east-1:0:log-group:/flashpoint/driver', 'tags': {'Project': 'flashpoint'}},
        ])
        kinds = {r['kind'] for r in client.get('/resources').json()['resources']}
        assert 'dynamodb' in kinds
        assert 'logs' in kinds


class TestConsoleLinks:
    def test_ec2_and_ebs_deep_links(self, client, mock_store, monkeypatch):
        monkeypatch.setattr(cost_data, 'list_instances', lambda: [{
            'id': 'i-123', 'type': 't4g.small', 'state': 'running',
            'launch_time': datetime.now() - timedelta(days=1),
        }])
        monkeypatch.setattr(cost_data, 'list_volumes', lambda: [{
            'id': 'vol-abc', 'state': 'in-use', 'size_gb': 20, 'type': 'gp3',
        }])
        rows = {r['kind']: r for r in client.get('/resources').json()['resources']}
        assert rows['ec2']['console_url'] == (
            'https://us-east-1.console.aws.amazon.com/ec2/home?region=us-east-1'
            '#InstanceDetails:instanceId=i-123'
        )
        assert rows['ebs']['console_url'].endswith('#VolumeDetails:volumeId=vol-abc')

    def test_fargate_links_task_details(self, client, mock_store, monkeypatch):
        monkeypatch.setattr(cost_data, 'list_running_tasks', lambda: [{
            'arn': 'arn:aws:ecs:us-east-1:0:task/flashpoint-dev/abc123',
            'role': 'spark-connect', 'started_at': datetime.now() - timedelta(hours=1),
            'cpu': '2048', 'memory': '8192',
        }])
        _seed_warehouse('my-wh', task_arn='arn:aws:ecs:us-east-1:0:task/flashpoint-dev/abc123')
        row = [r for r in client.get('/resources').json()['resources']
               if r['kind'] == 'fargate'][0]
        assert row['console_url'].endswith(
            '#/clusters/flashpoint-dev/tasks/abc123/details'
        )

    def test_unlinkable_ids_get_no_link(self, client, mock_store, monkeypatch):
        monkeypatch.setattr(cost_data, 'list_running_tasks', lambda: [{
            'arn': 'local-driver-mock', 'role': 'spark-connect',
            'started_at': datetime.now() - timedelta(hours=1),
            'cpu': '2048', 'memory': '8192',
        }])
        row = [r for r in client.get('/resources').json()['resources']
               if r['kind'] == 'fargate'][0]
        assert row['console_url'] is None
