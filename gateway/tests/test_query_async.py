"""Tests for async query execution, caching, cancel, status polling, and result fetch."""

import pytest
from unittest.mock import MagicMock

import query_runner
import routes_queries
import spark_client
import state
import store
from state import QueryStatus


@pytest.fixture(autouse=True)
def reset(mock_store):
    mock_store, _ = mock_store
    mock_store.clear()
    state.query_history.clear()
    spark_client._cache.clear()


def _put_warehouse(name='my-wh'):
    store.put_warehouse(
        name,
        {
            'task_arn': 'arn:driver',
            'task_ip': '10.0.0.5',
            'endpoint': 'sc://10.0.0.5:15002',
            'status': 'running',
            'size': 'XS',
            'executor_count': 1,
            'executor_arns': [],
            'created_at': 1717200000.0,
        },
    )


class TestAsyncQueryId:
    def test_stable_id(self, mock_store):
        _put_warehouse()
        a = routes_queries._async_query_id('SELECT 1', 'my-wh')
        b = routes_queries._async_query_id('SELECT 1', 'my-wh')
        assert a == b
        assert len(a) == 16

    def test_different_sql_different_id(self, mock_store):
        _put_warehouse()
        a = routes_queries._async_query_id('SELECT 1', 'my-wh')
        b = routes_queries._async_query_id('SELECT 2', 'my-wh')
        assert a != b

    def test_different_warehouse_different_id(self, mock_store):
        store.put_warehouse(
            'wh-a',
            {
                'task_arn': 'arn:a',
                'status': 'running',
                'size': 'XS',
                'executor_count': 1,
                'executor_arns': [],
                'created_at': 100.0,
            },
        )
        store.put_warehouse(
            'wh-b',
            {
                'task_arn': 'arn:b',
                'status': 'running',
                'size': 'XS',
                'executor_count': 1,
                'executor_arns': [],
                'created_at': 200.0,
            },
        )
        a = routes_queries._async_query_id('SELECT 1', 'wh-a')
        b = routes_queries._async_query_id('SELECT 1', 'wh-b')
        assert a != b

    def test_normalised_whitespace(self, mock_store):
        _put_warehouse()
        a = routes_queries._async_query_id('SELECT  1', 'my-wh')
        b = routes_queries._async_query_id('SELECT 1', 'my-wh')
        assert a == b


class TestAsyncSubmit:
    def test_returns_queued(self, client, mock_store, monkeypatch):
        monkeypatch.setattr(ecs_tasks, 'is_running', lambda arn: True)
        _put_warehouse()

        mock_runner = MagicMock()
        monkeypatch.setattr(query_runner, 'run_async_query', mock_runner)

        resp = client.post('/warehouses/my-wh/query/async', json={'sql': 'SELECT 1'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == QueryStatus.QUEUED
        assert len(data['query_id']) == 16
        mock_runner.assert_called_once()

    def test_cache_hit_returns_done(self, client, mock_store, monkeypatch):
        monkeypatch.setattr(ecs_tasks, 'is_running', lambda arn: True)
        _put_warehouse()

        qid = routes_queries._async_query_id('SELECT 1', 'my-wh')
        store.put_query_record(
            qid,
            {
                'warehouse_name': 'my-wh',
                'sql': 'SELECT 1',
                'status': QueryStatus.DONE,
                'row_count': 42,
                'duration_ms': 500,
                'submitted_at': 0,
                'ttl': 9999999999,
                's3_key': 'queries/a1b2/',
            },
        )

        resp = client.post('/warehouses/my-wh/query/async', json={'sql': 'SELECT 1'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == QueryStatus.DONE
        assert data['row_count'] == 42

    def test_in_flight_returns_running(self, client, mock_store, monkeypatch):
        monkeypatch.setattr(ecs_tasks, 'is_running', lambda arn: True)
        _put_warehouse()

        qid = routes_queries._async_query_id('SELECT 1', 'my-wh')
        store.put_query_record(
            qid,
            {
                'warehouse_name': 'my-wh',
                'sql': 'SELECT 1',
                'status': QueryStatus.RUNNING,
                'submitted_at': 0,
                'ttl': 9999999999,
            },
        )

        resp = client.post('/warehouses/my-wh/query/async', json={'sql': 'SELECT 1'})
        assert resp.status_code == 200
        assert resp.json()['status'] == QueryStatus.RUNNING

    def test_warehouse_not_found(self, client, mock_store):
        resp = client.post('/warehouses/nope/query/async', json={'sql': 'SELECT 1'})
        assert resp.status_code == 404

    def test_warehouse_not_running(self, client, mock_store, monkeypatch):
        monkeypatch.setattr(ecs_tasks, 'is_running', lambda arn: False)
        store.put_warehouse(
            'stopped-wh',
            {
                'task_arn': 'arn:dead',
                'status': 'suspended',
                'size': 'XS',
                'executor_count': 1,
                'executor_arns': [],
            },
        )
        resp = client.post('/warehouses/stopped-wh/query/async', json={'sql': 'SELECT 1'})
        assert resp.status_code == 409


class TestCancel:
    def test_cancel_specific_query(self, client, mock_store, monkeypatch):
        monkeypatch.setattr(ecs_tasks, 'is_running', lambda arn: True)
        _put_warehouse()
        monkeypatch.setattr(spark_client, 'interrupt', lambda name, qid: None)

        qid = 'abc123def4567890'
        store.put_query_record(
            qid, {'status': QueryStatus.RUNNING, 'submitted_at': 0, 'ttl': 9999999999}
        )

        resp = client.post(f'/warehouses/my-wh/query/cancel?qid={qid}')
        assert resp.status_code == 200
        assert resp.json()['status'] == 'cancelled'
        rec = store.get_query_record(qid)
        assert rec is not None
        assert rec['status'] == QueryStatus.CANCELLED

    def test_cancel_all(self, client, mock_store, monkeypatch):
        monkeypatch.setattr(ecs_tasks, 'is_running', lambda arn: True)
        _put_warehouse()
        interrupted = []

        def track_interrupt(name, qid):
            interrupted.append((name, qid))

        monkeypatch.setattr(spark_client, 'interrupt', track_interrupt)

        resp = client.post('/warehouses/my-wh/query/cancel')
        assert resp.status_code == 200
        assert interrupted == [('my-wh', None)]


class TestStatusPoll:
    def test_returns_query_record(self, client, mock_store):
        store.put_query_record(
            'abc123',
            {
                'warehouse_name': 'my-wh',
                'sql': 'SELECT 1',
                'status': QueryStatus.DONE,
                'row_count': 42,
                'duration_ms': 500,
                'submitted_at': 1717200000,
                'ttl': 9999999999,
            },
        )

        resp = client.get('/queries/abc123')
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == QueryStatus.DONE
        assert data['row_count'] == 42

    def test_not_found(self, client, mock_store):
        resp = client.get('/queries/nonexistent')
        assert resp.status_code == 404


class TestResultFetch:
    def test_redirects_to_s3(self, client, mock_store, monkeypatch):
        store.put_query_record(
            'abc123',
            {
                'warehouse_name': 'my-wh',
                'sql': 'SELECT 1',
                'status': QueryStatus.DONE,
                's3_key': 'queries/abc123/',
                'submitted_at': 0,
                'ttl': 9999999999,
            },
        )

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = 'https://s3.amazonaws.com/bucket/key'
        monkeypatch.setattr(routes_queries, 's3', mock_s3)

        resp = client.get('/queries/abc123/result', follow_redirects=False)
        assert resp.status_code == 302
        assert 's3.amazonaws.com' in resp.headers['location']

    def test_not_done_returns_409(self, client, mock_store):
        store.put_query_record(
            'abc123',
            {
                'status': QueryStatus.RUNNING,
                'submitted_at': 0,
                'ttl': 9999999999,
            },
        )
        resp = client.get('/queries/abc123/result')
        assert resp.status_code == 409


import ecs_tasks
