import pytest

from dag import (
    is_nonzero_size,
    metric_total,
    parse_duration_ms,
    transform_dag,
)

# ── metric_total ──────────────────────────────────────────────


class TestMetricTotal:
    def test_simple_value(self):
        assert metric_total('390 ms') == '390 ms'

    def test_aggregated_metric_returns_last_line(self):
        value = 'total (min, med, max)\n390 ms (200 ms, 350 ms, 550 ms)'
        assert metric_total(value) == '390 ms (200 ms, 350 ms, 550 ms)'

    def test_single_line(self):
        assert metric_total('16.6 KB (19.0 KB, 12.2 KB)') == '16.6 KB (19.0 KB, 12.2 KB)'

    def test_empty_string_returns_empty(self):
        assert metric_total('') == ''

    def test_whitespace_only(self):
        assert metric_total('   ') == ''

    def test_multiline_with_empty_last_line(self):
        value = 'header\n'
        assert metric_total(value) == 'header'


# ── parse_duration_ms ─────────────────────────────────────────


class TestParseDurationMs:
    def test_milliseconds(self):
        assert parse_duration_ms('390 ms') == 390

    def test_seconds(self):
        assert parse_duration_ms('2 s') == 2000

    def test_minutes(self):
        assert parse_duration_ms('1 min') == 60_000

    def test_minutes_short(self):
        assert parse_duration_ms('2 m') == 120_000

    def test_hours(self):
        assert parse_duration_ms('1 h') == 3_600_000

    def test_with_commas(self):
        assert parse_duration_ms('1,234 ms') == 1234

    def test_decimal(self):
        assert parse_duration_ms('1.5 s') == 1500

    def test_aggregated_metric(self):
        value = 'total (min, med, max)\n390 ms (200 ms, 350 ms, 550 ms)'
        assert parse_duration_ms(value) == 390

    def test_unparseable_returns_none(self):
        assert parse_duration_ms('N/A') is None

    def test_empty_returns_none(self):
        assert parse_duration_ms('') is None


# ── is_nonzero_size ───────────────────────────────────────────


class TestIsNonzeroSize:
    def test_nonzero(self):
        assert is_nonzero_size('512.0 KiB') is True

    def test_zero(self):
        assert is_nonzero_size('0.0 B') is False

    def test_zero_in_aggregate(self):
        value = 'total (min, med, max)\n0.0 B (0.0 B, 0.0 B, 0.0 B)'
        assert is_nonzero_size(value) is False

    def test_nonzero_in_aggregate(self):
        value = 'total (min, med, max)\n8.0 MiB (8.0 MiB, 8.0 MiB, 8.0 MiB)'
        assert is_nonzero_size(value) is True

    def test_unparseable_returns_false(self):
        assert is_nonzero_size('N/A') is False


# ── transform_dag ─────────────────────────────────────────────


class TestTransformDag:
    def test_empty_detail(self):
        result = transform_dag({})
        assert result == {'nodes': [], 'edges': []}

    def test_single_node_no_metrics(self):
        detail = {
            'nodes': [{'nodeId': 1, 'nodeName': 'Scan'}],
            'edges': [],
        }
        result = transform_dag(detail)
        assert len(result['nodes']) == 1
        node = result['nodes'][0]
        assert node['id'] == 1
        assert node['name'] == 'Scan'
        assert node['duration_ms'] is None
        assert node['is_shuffle'] is False
        assert node['has_skew'] is False
        assert node['has_spill'] is False
        assert node['metrics'] == {}

    def test_node_with_duration(self):
        detail = {
            'nodes': [
                {
                    'nodeId': 2,
                    'nodeName': 'Filter',
                    'metrics': [{'name': 'duration', 'value': '150 ms'}],
                }
            ],
            'edges': [],
        }
        result = transform_dag(detail)
        assert result['nodes'][0]['duration_ms'] == 150

    def test_shuffle_node_detected_by_name(self):
        detail = {
            'nodes': [{'nodeId': 3, 'nodeName': 'Exchange'}],
            'edges': [],
        }
        result = transform_dag(detail)
        assert result['nodes'][0]['is_shuffle'] is True

    def test_shuffle_node_detected_by_shuffle_name(self):
        detail = {
            'nodes': [{'nodeId': 4, 'nodeName': 'Shuffle Write'}],
            'edges': [],
        }
        result = transform_dag(detail)
        assert result['nodes'][0]['is_shuffle'] is True

    def test_shuffle_node_detected_by_metric(self):
        detail = {
            'nodes': [
                {
                    'nodeId': 5,
                    'nodeName': 'SomeStage',
                    'metrics': [{'name': 'shuffle bytes written', 'value': '1024.0 B'}],
                }
            ],
            'edges': [],
        }
        result = transform_dag(detail)
        assert result['nodes'][0]['is_shuffle'] is True

    def test_spill_detected(self):
        detail = {
            'nodes': [
                {
                    'nodeId': 6,
                    'nodeName': 'Aggregate',
                    'metrics': [{'name': 'spill size', 'value': '8.0 MiB'}],
                }
            ],
            'edges': [],
        }
        result = transform_dag(detail)
        assert result['nodes'][0]['has_spill'] is True

    def test_spill_zero_not_detected(self):
        detail = {
            'nodes': [
                {
                    'nodeId': 7,
                    'nodeName': 'Aggregate',
                    'metrics': [{'name': 'spill size', 'value': '0.0 B'}],
                }
            ],
            'edges': [],
        }
        result = transform_dag(detail)
        assert result['nodes'][0]['has_spill'] is False

    def test_sort_time_used_when_no_duration(self):
        detail = {
            'nodes': [
                {
                    'nodeId': 8,
                    'nodeName': 'Sort',
                    'metrics': [{'name': 'sort time', 'value': '200 ms'}],
                }
            ],
            'edges': [],
        }
        result = transform_dag(detail)
        assert result['nodes'][0]['duration_ms'] == 200

    def test_edges_preserved(self):
        detail = {
            'nodes': [
                {'nodeId': 1, 'nodeName': 'Scan'},
                {'nodeId': 2, 'nodeName': 'Exchange', 'metrics': []},
            ],
            'edges': [{'fromId': 1, 'toId': 2}],
        }
        result = transform_dag(detail)
        assert len(result['edges']) == 1
        assert result['edges'][0]['from'] == 1
        assert result['edges'][0]['to'] == 2
        assert result['edges'][0]['is_shuffle'] is False

    def test_edge_from_shuffle_node_flagged(self):
        detail = {
            'nodes': [
                {'nodeId': 3, 'nodeName': 'Exchange', 'metrics': []},
                {'nodeId': 4, 'nodeName': 'Aggregate', 'metrics': []},
            ],
            'edges': [{'fromId': 3, 'toId': 4}],
        }
        result = transform_dag(detail)
        assert result['edges'][0]['is_shuffle'] is True

    def test_metrics_included_in_output(self):
        detail = {
            'nodes': [
                {
                    'nodeId': 9,
                    'nodeName': 'Scan',
                    'metrics': [
                        {'name': 'number of output rows', 'value': '1000'},
                        {'name': 'scan time', 'value': '50 ms'},
                    ],
                }
            ],
            'edges': [],
        }
        result = transform_dag(detail)
        metrics = result['nodes'][0]['metrics']
        assert 'number of output rows' in metrics
        assert 'scan time' in metrics


# ── Duration unit parsing edge cases ───────────────────────────


class TestDurationEdgeCases:
    @pytest.mark.parametrize(
        'input_val,expected',
        [
            ('0 ms', 0),
            ('1,000 ms', 1000),
            ('0.5 s', 500),
            ('1.0 s', 1000),
            ('0 min', 0),
        ],
    )
    def test_various_durations(self, input_val, expected):
        assert parse_duration_ms(input_val) == expected
