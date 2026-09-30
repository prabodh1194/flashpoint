"""Try-it mode bounds — XS-only, no resize, session deadline."""

import time

import pytest

import ecs_tasks
import reconcile
import routes_warehouses
import store


@pytest.fixture
def tryit(monkeypatch):
    monkeypatch.setattr(routes_warehouses, 'TRYIT_MODE', True)
    monkeypatch.setattr(routes_warehouses, 'SESSION_MAX_S', 600)


@pytest.fixture
def launch(monkeypatch):
    calls: list[int] = []

    def _launch(warehouse_name, executor_count, grpc_port):
        calls.append(executor_count)
        arns = [f'arn:exec-{i}' for i in range(executor_count)]
        return 'arn:driver', '10.0.0.5', 'sc://10.0.0.5:15002', arns

    monkeypatch.setattr(ecs_tasks, 'launch_driver_with_executors', _launch)
    return calls


class TestCreate:
    def test_forces_xs_and_sets_deadline(self, client, tryit, launch, mock_store):
        before = time.time()
        resp = client.post('/warehouses', json={'name': 't1', 'size': 'L'})
        assert resp.status_code == 201
        assert resp.json()['size'] == 'XS'
        assert resp.json()['executor_count'] == 1
        assert launch == [1]
        rec = store.get_warehouse('t1')
        assert rec['size'] == 'XS'
        assert rec['session_deadline'] >= before + 600


class TestResize:
    def test_rejected_in_tryit(self, client, tryit, mock_store):
        store.put_warehouse(
            't1', {'status': 'running', 'size': 'XS', 'executor_count': 1, 'executor_arns': []}
        )
        resp = client.post('/warehouses/t1/resize', json={'size': 'M'})
        assert resp.status_code == 400


class TestReapReason:
    def test_session_deadline_wins(self):
        now = time.time()
        rec = {'created_at': now, 'session_deadline': now - 1}
        assert reconcile.reap_reason(rec, now, 7200) == 'session deadline'

    def test_idle_ttl(self):
        now = time.time()
        assert reconcile.reap_reason({'created_at': now - 7201}, now, 7200) == 'idle TTL'

    def test_fresh_record_kept(self):
        now = time.time()
        rec = {'created_at': now, 'session_deadline': now + 600}
        assert reconcile.reap_reason(rec, now, 7200) is None
