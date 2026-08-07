import pytest

from dag import (
    is_nonzero_size,
    metric_total,
    parse_column_treatments,
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


# ── parse_column_treatments ────────────────────────────────────

PLAN = """== Physical Plan ==
AdaptiveSparkPlan (5)
+- == Final Plan ==
   ResultQueryStage (4)
      +- * HashAggregate (3)
         +- * BroadcastHashJoin Inner BuildRight (2)
            :- * Filter (1)
            :  +- Scan parquet  (6)
            +- BroadcastQueryStage (7)
               +- BroadcastExchange (8)
                  +- * Filter (9)
                     +- Scan parquet  (10)
+- == Initial Plan ==
   HashAggregate (11)
   +- BroadcastHashJoin (12)
      +- Filter (13)
         +- Scan parquet  (6)

(1) Filter [codegen id : 2]
Input [1]: [customer_id#2]
Condition : isnotnull(customer_id#2)

(2) BroadcastHashJoin [codegen id : 2]
Left keys [1]: [customer_id#2]
Right keys [1]: [customer_id#6]
Join type: Inner
Join condition: None

(3) HashAggregate [codegen id : 2]
Input [1]: [region#3]
Keys [1]: [region#3]
Functions [1]: [count(1)]

(4) ResultQueryStage
Output [2]: [region#3, count(1)#4L]
Arguments: 2

(5) AdaptiveSparkPlan
Output [2]: [region#3, count(1)#4L]
Arguments: isFinalPlan=true

(6) Scan parquet 
Output [1]: [customer_id#2]
Batched: true
Location: InMemoryFileIndex [file:/tmp/spark-data/orders]
PushedFilters: [IsNotNull(customer_id)]
ReadSchema: struct<customer_id:int>

(7) BroadcastQueryStage
Output [2]: [customer_id#6, region#9]
Arguments: 0

(8) BroadcastExchange
Input [2]: [customer_id#6, region#9]
Arguments: HashedRelationBroadcastMode(List(cast(input[0, int, false] as bigint)),false)

(9) Filter [codegen id : 1]
Input [2]: [customer_id#6, region#9]
Condition : isnotnull(customer_id#6)

(10) Scan parquet 
Output [2]: [customer_id#6, region#9]
Batched: true
Location: InMemoryFileIndex [file:/tmp/spark-data/customers]
ReadSchema: struct<customer_id:int,region:string>

(11) HashAggregate
Input [1]: [region#3]
Keys [1]: [region#3]
Functions [1]: [count(1)]

(12) BroadcastHashJoin
Left keys [1]: [customer_id#2]
Right keys [1]: [customer_id#6]
Join type: Inner

(13) Filter
Input [1]: [customer_id#2]
Condition : isnotnull(customer_id#2)
"""

# Mirrors the Spark UI API's node array: execution order (data source first),
# with each WholeStageCodegen cluster sitting immediately after its members.
NODES = [
    {'nodeId': 12, 'nodeName': 'Scan parquet'},
    {'nodeId': 11, 'nodeName': 'ColumnarToRow'},
    {'nodeId': 10, 'nodeName': 'Filter'},
    {'nodeId': 9, 'nodeName': 'WholeStageCodegen (1)'},
    {'nodeId': 8, 'nodeName': 'BroadcastExchange'},
    {'nodeId': 6, 'nodeName': 'Scan parquet'},
    {'nodeId': 5, 'nodeName': 'ColumnarToRow'},
    {'nodeId': 4, 'nodeName': 'Filter'},
    {'nodeId': 3, 'nodeName': 'BroadcastHashJoin'},
    {'nodeId': 2, 'nodeName': 'HashAggregate'},
    {'nodeId': 7, 'nodeName': 'WholeStageCodegen (2)'},
    {'nodeId': 0, 'nodeName': 'AdaptiveSparkPlan'},
]


class TestColumnTreatments:
    def test_scan_block_maps_to_scan_node(self):
        t = parse_column_treatments(PLAN, NODES)
        node = t[12][0]
        assert node['operator'] == 'Scan parquet'
        keys = [e[0] for e in node['entries']]
        assert 'Output [2]' in keys
        assert 'ReadSchema' in keys
        assert 'Batched' not in keys  # noise line skipped

    def test_attribute_ids_stripped(self):
        t = parse_column_treatments(PLAN, NODES)
        node = t[12][0]
        output = next(e[1] for e in node['entries'] if e[0] == 'Output [2]')
        assert output == '[customer_id, region]'

    def test_join_treatment_kept(self):
        t = parse_column_treatments(PLAN, NODES)
        node = next(tr for tr in t[3] if tr['operator'] == 'BroadcastHashJoin')
        entries = dict(node['entries'])
        assert entries['Left keys [1]'] == '[customer_id]'
        assert entries['Join type'] == 'Inner'

    def test_codegen_blocks_map_to_member_nodes(self):
        t = parse_column_treatments(PLAN, NODES)
        assert t[2][0]['operator'] == 'HashAggregate'  # own node, not the cluster
        agg_keys = [e[0] for e in t[2][0]['entries']]
        assert 'Keys [1]' in agg_keys
        assert 'Functions [1]' in agg_keys
        assert t[3][0]['operator'] == 'BroadcastHashJoin'
        assert t[4][0]['operator'] == 'Filter'
        assert 7 not in t  # WholeStageCodegen (2) holds nothing anymore
        assert t[10][0]['operator'] == 'Filter'  # build side (codegen id 1)

    def test_scan_inside_codegen_gets_own_node(self):
        t = parse_column_treatments(PLAN, NODES)
        assert 6 in t
        assert t[6][0]['operator'] == 'Scan parquet'

    def test_initial_plan_blocks_excluded(self):
        t = parse_column_treatments(PLAN, NODES)
        all_ops = [tr['operator'] for node in t.values() for tr in node]
        assert 'HashAggregate' in all_ops  # final plan's, on its member node
        assert all_ops.count('Filter') == 2  # final plan's only (blocks 1 and 9)
        assert all_ops.count('BroadcastHashJoin') == 1  # final plan's only (block 2)

    def test_query_stage_blocks_skipped(self):
        t = parse_column_treatments(PLAN, NODES)
        ops = {tr['operator'] for node in t.values() for tr in node}
        assert 'ResultQueryStage' not in ops
        assert 'BroadcastQueryStage' not in ops

    def test_empty_plan_returns_empty(self):
        assert parse_column_treatments('', NODES) == {}

    def test_plan_without_final_section(self):
        plan = """== Physical Plan ==
Filter (2)
+- Scan parquet  (1)

(1) Scan parquet
Output [1]: [id#0L]
Batched: true

(2) Filter
Input [1]: [id#0L]
Condition : isnotnull(id#0L)
"""
        nodes = [{'nodeId': 0, 'nodeName': 'Filter'}, {'nodeId': 1, 'nodeName': 'Scan parquet'}]
        t = parse_column_treatments(plan, nodes)
        assert t[0][0]['operator'] == 'Filter'
        assert t[1][0]['operator'] == 'Scan parquet'

    def test_treatments_flow_through_transform_dag(self):
        detail = {
            'nodes': NODES,
            'edges': [],
            'planDescription': PLAN,
        }
        result = transform_dag(detail)
        by_id = {n['id']: n for n in result['nodes']}
        agg = by_id[2]['treatments'][0]
        assert agg['operator'] == 'HashAggregate'
        assert 'Keys [1]' in [e[0] for e in agg['entries']]
        assert by_id[3]['treatments'][0]['operator'] == 'BroadcastHashJoin'


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
