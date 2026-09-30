"""Budget guard tests — month rollup, kill switch, launch denial, guard stop."""

import time
from unittest.mock import MagicMock

import pytest

import budget
import meters
import reconcile
import store


def _day(offset_days: int = 0) -> str:
    return time.strftime('%Y-%m-%d', time.localtime(time.time() + offset_days * 86400))


@pytest.fixture
def meter_data(monkeypatch):
    """Budget reads an in-memory month instead of DynamoDB."""
    data: dict[str, dict[str, dict]] = {}
    monkeypatch.setattr(meters, 'list_meters', lambda days=30: data)
    return data


class TestMonthSpend:
    def test_sums_only_current_month(self, meter_data):
        meter_data['wh1'] = {_day(0): {'cost_usd': 0.5}, _day(-40): {'cost_usd': 9.0}}
        assert budget.month_spend_usd() == pytest.approx(0.5)

    def test_sums_across_warehouses(self, meter_data):
        meter_data['a'] = {_day(0): {'cost_usd': 1.25}}
        meter_data['b'] = {_day(0): {'cost_usd': 0.75}}
        assert budget.month_spend_usd() == pytest.approx(2.0)


class TestCanLaunch:
    def test_under_ceiling_allows(self, monkeypatch, meter_data):
        monkeypatch.setattr(budget, 'kill_switch', lambda: False)
        meter_data['wh1'] = {_day(0): {'cost_usd': 1.0}}
        assert budget.can_launch() is True

    def test_at_ceiling_minus_margin_denies(self, monkeypatch, meter_data):
        monkeypatch.setattr(budget, 'kill_switch', lambda: False)
        monkeypatch.setattr(budget, 'SPARK_BUDGET_USD', 3.0)
        monkeypatch.setattr(budget, 'SPARK_BUDGET_MARGIN_USD', 0.10)
        meter_data['wh1'] = {_day(0): {'cost_usd': 2.95}}
        assert budget.can_launch() is False

    def test_kill_switch_denies(self, monkeypatch, meter_data):
        monkeypatch.setattr(budget, 'kill_switch', lambda: True)
        assert budget.can_launch() is False


class TestEnforceBudget:
    def test_stops_running_warehouses_and_sets_switch(self, monkeypatch, mock_store, mock_ecs):
        store.put_warehouse(
            'wh1',
            {
                'status': 'running',
                'size': 'XS',
                'executor_count': 1,
                'task_arn': 'arn:driver',
                'executor_arns': ['arn:exec'],
                'session_started_at': time.time() - 60,
                'last_metered_at': time.time() - 60,
            },
        )
        monkeypatch.setattr(budget, 'can_launch', lambda: False)
        monkeypatch.setattr(budget, 'month_spend_usd', lambda now=None: 9.0)
        switched: list[bool] = []
        monkeypatch.setattr(budget, 'set_kill_switch', lambda on=True: switched.append(on))

        stopped = reconcile.enforce_budget(MagicMock(), 'test-cluster')

        assert stopped == 1
        assert switched == [True]
        assert store.get_warehouse('wh1')['status'] == 'suspended'
        stopped_arns = [call.kwargs['task'] for call in mock_ecs.stop_task.call_args_list]
        assert stopped_arns == ['arn:driver', 'arn:exec']

    def test_noop_when_budget_healthy(self, monkeypatch, mock_store, mock_ecs):
        store.put_warehouse(
            'wh1',
            {'status': 'running', 'size': 'XS', 'task_arn': 'arn:driver', 'executor_arns': []},
        )
        monkeypatch.setattr(budget, 'can_launch', lambda: True)

        assert reconcile.enforce_budget(MagicMock(), 'test-cluster') == 0
        assert store.get_warehouse('wh1')['status'] == 'running'
        mock_ecs.stop_task.assert_not_called()


class TestLaunchDenial:
    def test_create_returns_429_when_exhausted(self, client, monkeypatch, mock_store, mock_ecs):
        monkeypatch.setattr(budget, 'can_launch', lambda: False)
        resp = client.post('/warehouses', json={'name': 'blocked'})
        assert resp.status_code == 429
        assert 'budget' in resp.json()['detail']

    def test_resume_returns_429_when_exhausted(self, client, monkeypatch, mock_store, mock_ecs):
        store.put_warehouse(
            'wh1', {'status': 'suspended', 'size': 'XS', 'executor_count': 1, 'executor_arns': []}
        )
        monkeypatch.setattr(budget, 'can_launch', lambda: False)
        resp = client.post('/warehouses/wh1/resume')
        assert resp.status_code == 429
