from unittest.mock import MagicMock

import pytest

import ecs_tasks
import routes_queries
import routes_warehouses
import spark_client
import state
import store


@pytest.fixture(autouse=True)
def reset_state(mock_store):
    mock_store, _ = mock_store
    mock_store.clear()
    state.query_history.clear()
    spark_client._cache.clear()


@pytest.fixture
def mock_create_warehouse_deps(monkeypatch, mock_ecs):
    def _launch(warehouse_name, executor_count, grpc_port):
        arns = [f'arn:exec-{i}' for i in range(executor_count)]
        return 'arn:driver-1', '10.0.0.5', 'sc://10.0.0.5:15002', arns

    monkeypatch.setattr(ecs_tasks, 'launch_driver_with_executors', _launch)


class TestHealthz:
    def test_health_ok(self, client, mock_store):
        resp = client.get('/healthz')
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'ok'
        assert 'warehouses' in data


class TestCreateWarehouse:
    def test_creates_default_xs(self, client, mock_create_warehouse_deps, mock_store):
        resp = client.post('/warehouses', json={'name': 'test-wh'})
        assert resp.status_code == 201
        data = resp.json()
        assert data['name'] == 'test-wh'
        assert data['status'] == 'running'
        assert data['size'] == 'XS'
        assert data['executor_count'] == 1
        assert data['endpoint'] == 'sc://10.0.0.5:15002'
        assert store.get_warehouse('test-wh') is not None

    def test_creates_custom_size(self, client, mock_create_warehouse_deps, mock_store):
        resp = client.post('/warehouses', json={'name': 'test-wh', 'size': 'M'})
        assert resp.status_code == 201
        data = resp.json()
        assert data['size'] == 'M'
        assert data['executor_count'] == 4

    def test_rejects_unknown_size(self, client, mock_store):
        resp = client.post('/warehouses', json={'name': 'bad', 'size': 'XXL'})
        assert resp.status_code == 400

    def test_warehouse_cap(self, client, monkeypatch, mock_store):
        monkeypatch.setattr(routes_warehouses, 'MAX_WAREHOUSES', 1)
        monkeypatch.setattr(
            ecs_tasks,
            'launch_driver_with_executors',
            lambda warehouse_name, executor_count, grpc_port: ('arn:x', '10.0.0.1', 'sc://10.0.0.1:15002', []),
        )
        store.put_warehouse(
            'existing',
            {
                'task_arn': 'arn:1',
                'status': 'running',
                'size': 'XS',
                'executor_count': 1,
                'executor_arns': [],
                'created_at': 0,
            },
        )
        resp = client.post('/warehouses', json={'name': 'test-wh'})
        assert resp.status_code == 429

    def test_rejects_duplicate_name(self, client, mock_store):
        store.put_warehouse(
            'existing',
            {
                'task_arn': 'arn:1',
                'status': 'running',
                'size': 'XS',
                'executor_count': 1,
                'executor_arns': [],
                'created_at': 0,
            },
        )
        resp = client.post('/warehouses', json={'name': 'existing', 'size': 'XS'})
        assert resp.status_code == 409

    def test_duplicate_concurrent_create_does_not_launch(self, client, monkeypatch, mock_store):
        launched: list[str] = []

        def _launch(warehouse_name, executor_count, grpc_port):
            launched.append(warehouse_name)
            return 'arn:driver-1', '10.0.0.5', 'sc://10.0.0.5:15002', []

        monkeypatch.setattr(ecs_tasks, 'launch_driver_with_executors', _launch)
        client.post('/warehouses', json={'name': 'dup-wh', 'size': 'XS'})
        resp = client.post('/warehouses', json={'name': 'dup-wh', 'size': 'XS'})
        assert resp.status_code == 409
        assert launched == ['dup-wh']

    def test_launch_failure_rolls_back(self, client, monkeypatch, mock_store):
        _db, _ = mock_store
        stopped: list[str] = []

        def _boom(warehouse_name, executor_count, grpc_port):
            raise RuntimeError('run_task exploded')

        monkeypatch.setattr(ecs_tasks, 'launch_driver_with_executors', _boom)
        monkeypatch.setattr(ecs_tasks, 'stop_orphan_tasks', lambda name: stopped.append(name))

        resp = client.post('/warehouses', json={'name': 'rollback-wh', 'size': 'XS'})
        assert resp.status_code == 500
        assert store.get_warehouse('rollback-wh') is None
        assert stopped == ['rollback-wh']


class TestListWarehouses:
    def test_empty(self, client, mock_store):
        resp = client.get('/warehouses')
        assert resp.status_code == 200
        data = resp.json()
        assert data['warehouses'] == []
        assert data['count'] == 0

    def test_with_warehouses(self, client, mock_store):
        store.put_warehouse(
            'wh1',
            {
                'task_arn': 'arn:1',
                'status': 'running',
                'size': 'XS',
                'executor_count': 1,
                'executor_arns': [],
                'created_at': 0,
            },
        )
        store.put_warehouse(
            'wh2',
            {
                'task_arn': 'arn:2',
                'status': 'running',
                'size': 'S',
                'executor_count': 2,
                'executor_arns': [],
                'created_at': 0,
            },
        )
        resp = client.get('/warehouses')
        assert resp.status_code == 200
        data = resp.json()
        assert len(data['warehouses']) == 2
        assert data['count'] == 2


class TestGetWarehouse:
    def test_found_running(self, client, monkeypatch, mock_store):
        monkeypatch.setattr(ecs_tasks, 'is_running', lambda arn: True)
        store.put_warehouse(
            'my-wh',
            {
                'task_arn': 'arn:1',
                'endpoint': 'sc://10.0.0.5:15002',
                'status': 'running',
                'size': 'S',
                'executor_count': 2,
                'executor_arns': [],
            },
        )
        resp = client.get('/warehouses/my-wh')
        assert resp.status_code == 200
        data = resp.json()
        assert data['name'] == 'my-wh'
        assert data['status'] == 'running'

    def test_not_found(self, client, mock_store):
        resp = client.get('/warehouses/nonexistent')
        assert resp.status_code == 404

    def test_suspended(self, client, monkeypatch, mock_store):
        monkeypatch.setattr(ecs_tasks, 'is_running', lambda arn: False)
        store.put_warehouse(
            'my-wh',
            {
                'task_arn': '',
                'endpoint': None,
                'status': 'suspended',
                'size': 'XS',
                'executor_count': 1,
                'executor_arns': [],
            },
        )
        resp = client.get('/warehouses/my-wh')
        assert resp.status_code == 200
        assert resp.json()['status'] == 'suspended'


class TestRunQuery:
    @pytest.fixture(autouse=True)
    def setup_warehouse(self, monkeypatch, mock_store):
        monkeypatch.setattr(ecs_tasks, 'is_running', lambda arn: True)
        store.put_warehouse(
            'my-wh',
            {
                'task_arn': 'arn:driver',
                'task_ip': '10.0.0.5',
                'endpoint': 'sc://10.0.0.5:15002',
                'status': 'running',
                'size': 'XS',
                'executor_count': 1,
                'executor_arns': [],
            },
        )

    def test_runs_query(self, client, monkeypatch):
        mock_spark = MagicMock()
        mock_df = MagicMock()
        mock_df.columns = ['id', 'name']
        mock_df.collect.return_value = [['1', 'alice']]
        mock_spark.sql.return_value = mock_df
        monkeypatch.setattr(spark_client, 'get', lambda endpoint, name: mock_spark)
        monkeypatch.setattr(routes_queries, '_fetch_query_dag', lambda s, sql: None)
        monkeypatch.setattr(routes_queries, '_fetch_query_dag', lambda s, sql: None)

        resp = client.post('/warehouses/my-wh/query', json={'sql': 'SELECT 1'})
        assert resp.status_code == 200
        data = resp.json()
        assert data['columns'] == ['id', 'name']
        assert data['row_count'] == 1
        assert len(data['query_id']) == 16

    def test_not_found(self, client, mock_store):
        resp = client.post('/warehouses/nope/query', json={'sql': 'SELECT 1'})
        assert resp.status_code == 404

    def test_not_running(self, client, monkeypatch, mock_store):
        monkeypatch.setattr(ecs_tasks, 'is_running', lambda arn: False)
        store.put_warehouse(
            'stopped-wh',
            {
                'task_arn': 'arn:dead',
                'endpoint': 'sc://10.0.0.5:15002',
                'status': 'suspended',
                'size': 'XS',
                'executor_count': 1,
                'executor_arns': [],
            },
        )
        resp = client.post('/warehouses/stopped-wh/query', json={'sql': 'SELECT 1'})
        assert resp.status_code == 409

    def test_spark_error(self, client, monkeypatch):
        mock_spark = MagicMock()
        mock_spark.sql.side_effect = Exception('table not found: bad_table')
        monkeypatch.setattr(spark_client, 'get', lambda endpoint, name: mock_spark)
        monkeypatch.setattr(routes_queries, '_fetch_query_dag', lambda s, sql: None)

        resp = client.post('/warehouses/my-wh/query', json={'sql': 'SELECT * FROM bad_table'})
        assert resp.status_code == 400

    def test_records_failed_query(self, client, monkeypatch):
        mock_spark = MagicMock()
        mock_spark.sql.side_effect = Exception('fail')
        monkeypatch.setattr(spark_client, 'get', lambda endpoint, name: mock_spark)
        monkeypatch.setattr(routes_queries, '_fetch_query_dag', lambda s, sql: None)

        client.post('/warehouses/my-wh/query', json={'sql': 'bad'})
        assert len(state.query_history) == 1
        assert state.query_history[0]['status'] == 'failed'

    def test_query_times_out(self, client, monkeypatch):
        import threading

        monkeypatch.setattr(routes_queries, 'QUERY_TIMEOUT_S', 1)

        mock_spark = MagicMock()
        mock_df = MagicMock()
        mock_df.columns = ['x']
        mock_df.collect.side_effect = lambda: threading.Event().wait(5)
        mock_spark.sql.return_value = mock_df
        monkeypatch.setattr(spark_client, 'get', lambda endpoint, name: mock_spark)
        interrupted: list[str] = []
        monkeypatch.setattr(
            spark_client, 'interrupt', lambda name, qid=None: interrupted.append(qid)
        )

        resp = client.post('/warehouses/my-wh/query', json={'sql': 'SELECT slow()'})
        assert resp.status_code == 504
        assert 'timed out' in resp.json()['detail']
        assert len(interrupted) == 1
        assert any(
            e['status'] == 'failed' and 'timed out' in e.get('error', '')
            for e in state.query_history
        )


class TestDeleteWarehouse:
    def test_deletes(self, client, monkeypatch, mock_store):
        monkeypatch.setattr(spark_client, 'drop', lambda name: None)
        monkeypatch.setattr(ecs_tasks, 'stop_tasks', lambda s: None)
        store.put_warehouse(
            'my-wh',
            {
                'task_arn': 'arn:d',
                'executor_arns': [],
                'status': 'running',
                'size': 'XS',
                'executor_count': 1,
            },
        )

        resp = client.delete('/warehouses/my-wh')
        assert resp.status_code == 204
        assert store.get_warehouse('my-wh') is None

    def test_not_found(self, client, mock_store):
        resp = client.delete('/warehouses/nonexistent')
        assert resp.status_code == 404


class TestSuspendResume:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch, mock_store):
        monkeypatch.setattr(spark_client, 'drop', lambda name: None)
        monkeypatch.setattr(ecs_tasks, 'stop_tasks', lambda s: None)
        store.put_warehouse(
            'my-wh',
            {
                'task_arn': 'arn:d',
                'executor_arns': ['arn:e1'],
                'task_ip': '10.0.0.5',
                'endpoint': 'sc://10.0.0.5:15002',
                'status': 'running',
                'size': 'S',
                'executor_count': 2,
            },
        )

    def test_suspend(self, client):
        resp = client.post('/warehouses/my-wh/suspend')
        assert resp.status_code == 200
        assert resp.json()['status'] == 'suspended'
        wh = store.get_warehouse('my-wh')
        assert wh is not None
        assert wh['status'] == 'suspended'

    def test_suspend_already_suspended(self, client, mock_store):
        store.update_warehouse_status('my-wh', 'suspended')
        resp = client.post('/warehouses/my-wh/suspend')
        assert resp.status_code == 200

    def test_suspend_not_found(self, client, mock_store):
        resp = client.post('/warehouses/nope/suspend')
        assert resp.status_code == 404

    def test_resume(self, client, monkeypatch, mock_store):
        store.update_warehouse_status('my-wh', 'suspended')
        monkeypatch.setattr(
            ecs_tasks,
            'launch_driver_with_executors',
            lambda warehouse_name, executor_count, grpc_port: (
                'arn:new-driver',
                '10.0.0.6',
                'sc://10.0.0.6:15002',
                [f'arn:new-exec-{i}' for i in range(executor_count)],
            ),
        )

        resp = client.post('/warehouses/my-wh/resume')
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'running'
        assert data['endpoint'] == 'sc://10.0.0.6:15002'

    def test_resume_already_running(self, client):
        resp = client.post('/warehouses/my-wh/resume')
        assert resp.status_code == 200
        assert resp.json()['status'] == 'running'


class TestResize:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch, mock_store):
        monkeypatch.setattr(ecs_tasks, 'is_running', lambda arn: True)
        store.put_warehouse(
            'my-wh',
            {
                'task_arn': 'arn:d',
                'executor_arns': ['arn:e1', 'arn:e2'],
                'task_ip': '10.0.0.5',
                'endpoint': 'sc://10.0.0.5:15002',
                'status': 'running',
                'size': 'S',
                'executor_count': 2,
            },
        )

    def test_scale_up(self, client, monkeypatch):
        monkeypatch.setattr(
            ecs_tasks,
            'run_executor_tasks',
            lambda url, count, name: [f'arn:new-{i}' for i in range(count)],
        )
        resp = client.post('/warehouses/my-wh/resize', json={'size': 'M'})
        assert resp.status_code == 200
        wh = store.get_warehouse('my-wh')
        assert wh is not None
        assert wh['executor_count'] == 4
        assert wh['size'] == 'M'

    def test_scale_down(self, client, mock_ecs):
        resp = client.post('/warehouses/my-wh/resize', json={'size': 'XS'})
        assert resp.status_code == 200
        wh = store.get_warehouse('my-wh')
        assert wh is not None
        assert wh['executor_count'] == 1
        assert wh['size'] == 'XS'

    def test_unknown_size(self, client):
        resp = client.post('/warehouses/my-wh/resize', json={'size': 'XXL'})
        assert resp.status_code == 400

    def test_not_running(self, client, mock_store):
        store.update_warehouse_status('my-wh', 'suspended')
        resp = client.post('/warehouses/my-wh/resize', json={'size': 'M'})
        assert resp.status_code == 409


class TestHistory:
    def test_empty(self, client):
        resp = client.get('/history')
        assert resp.status_code == 200
        data = resp.json()
        assert data['history'] == []
        assert data['count'] == 0

    def test_with_entries(self, client):
        state.query_history.append(
            {
                'query_id': 'abc123',
                'sql': 'SELECT 1',
                'status': 'success',
                'duration_ms': 100,
                'row_count': 1,
                'name': 'my-wh',
                'ts': '12:00:00',
            }
        )
        resp = client.get('/history')
        assert resp.status_code == 200
        data = resp.json()
        assert len(data['history']) == 1

    def test_history_entry_found(self, client):
        state.query_history.append({'query_id': 'abc', 'sql': 'SELECT 1'})
        resp = client.get('/history/abc')
        assert resp.status_code == 200

    def test_history_entry_not_found(self, client):
        resp = client.get('/history/nonexistent')
        assert resp.status_code == 404

    def test_clear(self, client):
        state.query_history.append({'query_id': 'abc', 'sql': 'SELECT 1'})
        resp = client.delete('/history')
        assert resp.status_code == 204
        assert len(state.query_history) == 0
