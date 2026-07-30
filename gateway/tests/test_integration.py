import time
import urllib.request
from unittest.mock import MagicMock, patch

import dag
import main
import reconcile
import spark_client
import store


class TestUiGet:
    def test_returns_parsed_json(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'[{"id": "app-1"}, {"id": "app-2"}]'
        mock_resp.__enter__.return_value = mock_resp

        with patch.object(urllib.request, 'urlopen', return_value=mock_resp):
            result = dag._ui_get('10.0.0.5', '/applications')
            assert result == [{'id': 'app-1'}, {'id': 'app-2'}]

    def test_uses_correct_url(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{}'
        mock_resp.__enter__.return_value = mock_resp

        with patch.object(urllib.request, 'urlopen') as mock_urlopen:
            mock_urlopen.return_value = mock_resp
            dag._ui_get('10.0.0.5', '/applications/app-1/sql')
            mock_urlopen.assert_called_once()
            args, _kw = mock_urlopen.call_args
            assert args[0] == 'http://10.0.0.5:4040/api/v1/applications/app-1/sql'


class TestResolveAppId:
    def test_returns_first_running_app(self, monkeypatch):
        monkeypatch.setattr(
            dag,
            '_ui_get',
            lambda ip, path: [
                {'id': 'app-1', 'attempts': [{'completed': False}]},
                {'id': 'app-2', 'attempts': [{'completed': True}]},
            ],
        )
        result = dag.resolve_app_id('10.0.0.5')
        assert result == 'app-1'

    def test_no_apps_returns_none(self, monkeypatch):
        monkeypatch.setattr(dag, '_ui_get', lambda ip, path: [])
        result = dag.resolve_app_id('10.0.0.5')
        assert result is None

    def test_falls_back_to_first_when_all_completed(self, monkeypatch):
        monkeypatch.setattr(
            dag,
            '_ui_get',
            lambda ip, path: [
                {'id': 'app-1', 'attempts': [{'completed': True}]},
            ],
        )
        result = dag.resolve_app_id('10.0.0.5')
        assert result == 'app-1'


class TestFetchQueryDagByQid:
    def test_finds_by_sql_description(self, monkeypatch):
        def mock_ui(ip, path):
            if '?details=true' in path:
                return {'nodes': [{'nodeId': 1, 'nodeName': 'Scan', 'metrics': []}], 'edges': []}
            return [{'id': 42, 'status': 'COMPLETED', 'description': 'SELECT * FROM users'}]

        monkeypatch.setattr(dag, '_ui_get', mock_ui)
        result = dag.fetch_query_dag_by_qid('10.0.0.5', 'SELECT * FROM users', 'app-1')
        assert result is not None
        assert len(result['nodes']) == 1

    def test_matches_normalised_whitespace(self, monkeypatch):
        def mock_ui(ip, path):
            if '?details=true' in path:
                return {'nodes': [{'nodeId': 1, 'nodeName': 'Scan', 'metrics': []}], 'edges': []}
            return [{'id': 1, 'status': 'COMPLETED', 'description': 'SELECT  *\nFROM    users'}]

        monkeypatch.setattr(dag, '_ui_get', mock_ui)
        result = dag.fetch_query_dag_by_qid('10.0.0.5', 'SELECT * FROM users', 'app-1')
        assert result is not None

    def test_skips_non_matching(self, monkeypatch):
        monkeypatch.setattr(
            dag,
            '_ui_get',
            lambda ip, path: [{'id': 1, 'status': 'COMPLETED', 'description': 'SELECT 1'}],
        )
        monkeypatch.setattr(time, 'sleep', lambda s: None)
        result = dag.fetch_query_dag_by_qid('10.0.0.5', 'SELECT 2', 'app-1')
        assert result is None

    def test_returns_none_when_no_app_id(self, monkeypatch):
        monkeypatch.setattr(dag, 'resolve_app_id', lambda ip: None)
        result = dag.fetch_query_dag_by_qid('10.0.0.5', 'SELECT 1')
        assert result is None

    def test_returns_none_on_timeout(self, monkeypatch):
        monkeypatch.setattr(
            dag,
            '_ui_get',
            lambda ip, path: [{'id': 1, 'status': 'RUNNING', 'description': 'SELECT 1'}],
        )
        monkeypatch.setattr(dag, '_FETCH_TIMEOUT_S', 0.1)
        result = dag.fetch_query_dag_by_qid('10.0.0.5', 'SELECT 1', 'app-1')
        assert result is None

    def test_returns_none_on_exception(self, monkeypatch):
        monkeypatch.setattr(
            dag, '_ui_get', lambda ip, path: (_ for _ in ()).throw(Exception('boom'))
        )
        result = dag.fetch_query_dag_by_qid('10.0.0.5', 'SELECT 1', 'app-1')
        assert result is None


class TestGetSpark:
    def test_creates_new_session(self, monkeypatch):
        mock_builder = MagicMock()
        mock_builder.remote.return_value.getOrCreate.return_value = 'spark-instance'
        monkeypatch.setattr(spark_client.SparkSession, 'builder', mock_builder)

        result = spark_client.get('s1', 'sc://10.0.0.5:15002')
        assert result == 'spark-instance'

    def test_caches_session(self, monkeypatch):
        mock_builder = MagicMock()
        mock_builder.remote.return_value.getOrCreate.return_value = 'spark-1'
        monkeypatch.setattr(spark_client.SparkSession, 'builder', mock_builder)
        spark_client._cache.clear()

        spark_client.get('s1', 'sc://10.0.0.5:15002')
        spark_client.get('s1', 'sc://10.0.0.5:15002')
        # builder should be called only once
        mock_builder.remote.assert_called_once()

    def test_drop_spark_stops_and_removes(self):
        mock_spark = MagicMock()
        spark_client._cache['s1'] = mock_spark
        spark_client.drop('s1')
        mock_spark.stop.assert_called_once()
        assert 's1' not in spark_client._cache

    def test_drop_spark_handles_stop_error(self):
        mock_spark = MagicMock()
        mock_spark.stop.side_effect = Exception('stop failed')
        spark_client._cache['s1'] = mock_spark
        spark_client.drop('s1')
        assert 's1' not in spark_client._cache

    def test_drop_spark_nonexistent(self):
        spark_client.drop('nonexistent')
        # should not raise


class TestReconcile:
    def test_reconcile_skips_suspended(self, monkeypatch, mock_ecs):
        monkeypatch.setattr(
            store,
            'list_warehouses',
            lambda: [
                {'name': 's1', 'task_arn': 'arn:old', 'status': 'suspended'},
            ],
        )
        reconcile.reconcile(main.CLUSTER)

    def test_reconcile_live_driver(self, monkeypatch, mock_ecs):
        monkeypatch.setattr(
            store,
            'list_warehouses',
            lambda: [
                {
                    'name': 's1',
                    'task_arn': 'arn:live',
                    'status': 'running',
                    'executor_arns': [],
                    'task_ip': '10.0.0.5',
                    'endpoint': 'sc://10.0.0.5:15002',
                },
            ],
        )
        mock_ecs.get_paginator.return_value.paginate.return_value = [
            {'taskArns': ['arn:live']},
        ]
        reconcile.reconcile(main.CLUSTER)

    def test_reconcile_suspends_dead_driver(self, monkeypatch, mock_ecs):
        monkeypatch.setattr(
            store,
            'list_warehouses',
            lambda: [
                {
                    'name': 's1',
                    'task_arn': 'arn:dead',
                    'status': 'running',
                    'executor_arns': [],
                    'task_ip': '10.0.0.5',
                },
            ],
        )
        monkeypatch.setattr(store, 'update_warehouse_status', lambda *a, **kw: None)
        mock_ecs.get_paginator.return_value.paginate.return_value = [
            {'taskArns': []},
        ]
        reconcile.reconcile(main.CLUSTER)

    def test_reconcile_stops_orphan_tasks(self, monkeypatch, mock_ecs):
        monkeypatch.setattr(store, 'list_warehouses', list)
        mock_ecs.get_paginator.return_value.paginate.return_value = [
            {'taskArns': ['arn:orphan']},
        ]
        reconcile.reconcile(main.CLUSTER)
        mock_ecs.stop_task.assert_called_with(
            cluster=main.CLUSTER, task='arn:orphan', reason='orphan-cleanup'
        )

    def test_reconcile_handles_ecs_error(self, monkeypatch, mock_ecs):
        mock_ecs.get_paginator.side_effect = Exception('ECS down')
        monkeypatch.setattr(store, 'list_warehouses', list)
        reconcile.reconcile(main.CLUSTER)
        # should not raise
