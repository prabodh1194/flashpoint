from unittest.mock import MagicMock

import pytest

import ecs_tasks


class TestRunDriverTask:
    def test_returns_task_arn(self, mock_ecs):
        mock_ecs.run_task.return_value = {
            'tasks': [{'taskArn': 'arn:aws:ecs:us-east-1:123456789:task/test/abc123'}],
            'failures': [],
        }
        result = ecs_tasks.run_driver_task("test-wh")
        assert result == 'arn:aws:ecs:us-east-1:123456789:task/test/abc123'

    def test_raises_on_failure(self, mock_ecs):
        mock_ecs.run_task.return_value = {
            'tasks': [],
            'failures': [{'arn': '...', 'reason': 'capacity'}],
        }
        with pytest.raises(RuntimeError, match='RunTask failed'):
            ecs_tasks.run_driver_task("test-wh")

    def test_uses_fargate_launch_type(self, mock_ecs):
        mock_ecs.run_task.return_value = {
            'tasks': [{'taskArn': 'arn:test'}],
            'failures': [],
        }
        ecs_tasks.run_driver_task("test-wh")
        call_kwargs = mock_ecs.run_task.call_args.kwargs
        assert call_kwargs['launchType'] == 'FARGATE'


class TestWaitRunning:
    def test_waits_for_running(self, mock_ecs):
        mock_ecs.get_waiter.return_value = MagicMock()
        ecs_tasks.wait_running('arn:test')
        mock_ecs.get_waiter.assert_called_once_with('tasks_running')
        mock_ecs.get_waiter.return_value.wait.assert_called_once()


class TestPrivateIp:
    def test_extracts_private_ip(self, mock_ecs):
        mock_ecs.describe_tasks.return_value = {
            'tasks': [
                {
                    'taskArn': 'arn:test',
                    'lastStatus': 'RUNNING',
                    'attachments': [
                        {
                            'details': [
                                {'name': 'privateIPv4Address', 'value': '10.0.1.42'},
                                {'name': 'subnetId', 'value': 'subnet-abc'},
                            ],
                        }
                    ],
                }
            ],
        }
        result = ecs_tasks.private_ip('arn:test')
        assert result == '10.0.1.42'


class TestIsRunning:
    def test_running_task(self, mock_ecs):
        mock_ecs.describe_tasks.return_value = {
            'tasks': [{'lastStatus': 'RUNNING'}],
        }
        assert ecs_tasks.is_running('arn:test') is True

    def test_stopped_task(self, mock_ecs):
        mock_ecs.describe_tasks.return_value = {
            'tasks': [{'lastStatus': 'STOPPED'}],
        }
        assert ecs_tasks.is_running('arn:test') is False

    def test_no_tasks(self, mock_ecs):
        mock_ecs.describe_tasks.return_value = {'tasks': []}
        assert ecs_tasks.is_running('arn:test') is False


class TestRunExecutorTasks:
    def test_launches_n_executors(self, mock_ecs):
        mock_ecs.run_task.return_value = {
            'tasks': [
                {'taskArn': 'arn:exec-1'},
                {'taskArn': 'arn:exec-2'},
                {'taskArn': 'arn:exec-3'},
            ],
            'failures': [],
        }
        result = ecs_tasks.run_executor_tasks('spark://10.0.0.1:7077', 3, "test-wh")
        assert len(result) == 3
        assert result == ['arn:exec-1', 'arn:exec-2', 'arn:exec-3']
        assert mock_ecs.run_task.call_args.kwargs['count'] == 3

    def test_uses_spot_capacity(self, mock_ecs):
        mock_ecs.run_task.return_value = {
            'tasks': [{'taskArn': 'arn:exec'}],
            'failures': [],
        }
        ecs_tasks.run_executor_tasks('spark://10.0.0.1:7077', 1, "test-wh")
        call_kwargs = mock_ecs.run_task.call_args.kwargs
        strategies = call_kwargs['capacityProviderStrategy']
        assert any(s['capacityProvider'] == 'FARGATE_SPOT' for s in strategies)

    def test_passes_master_url_to_container(self, mock_ecs):
        mock_ecs.run_task.return_value = {
            'tasks': [{'taskArn': 'arn:exec'}],
            'failures': [],
        }
        ecs_tasks.run_executor_tasks('spark://10.0.0.1:7077', 1, "test-wh")
        call_kwargs = mock_ecs.run_task.call_args.kwargs
        overrides = call_kwargs['overrides']['containerOverrides'][0]
        env = {e['name']: e['value'] for e in overrides['environment']}
        assert env['SPARK_MASTER_URL'] == 'spark://10.0.0.1:7077'

    def test_survives_partial_failures(self, mock_ecs):
        mock_ecs.run_task.return_value = {
            'tasks': [
                {'taskArn': 'arn:ok-1'},
                {'taskArn': 'arn:ok-2'},
            ],
            'failures': [
                {'arn': 'arn:bad', 'reason': 'capacity'},
            ],
        }
        result = ecs_tasks.run_executor_tasks('spark://10.0.0.1:7077', 3, "test-wh")
        assert result == ['arn:ok-1', 'arn:ok-2']


class TestStopTasks:
    def test_stops_driver_and_executors(self, mock_ecs):
        s = {
            'task_arn': 'arn:driver',
            'executor_arns': ['arn:exec-1', 'arn:exec-2'],
        }
        ecs_tasks.stop_tasks(s)
        assert mock_ecs.stop_task.call_count == 3

    def test_stop_task_failure_not_fatal(self, mock_ecs):
        mock_ecs.stop_task.side_effect = Exception('boom')
        s = {'task_arn': 'arn:driver', 'executor_arns': []}
        ecs_tasks.stop_tasks(s)
        # should not raise

    def test_no_task_arn(self, mock_ecs):
        ecs_tasks.stop_tasks({'task_arn': None, 'executor_arns': []})
        mock_ecs.stop_task.assert_not_called()
