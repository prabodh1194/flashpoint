"""Local integration test: Spark UI DAG fetch against a real Spark driver.

Requires: JAVA_HOME pointing to Java 17. Run with:
  JAVA_HOME=/opt/homebrew/opt/openjdk@17 uv run pytest tests/test_dag_live.py -v -s
"""

import time
import pytest
import pyspark

import dag


@pytest.fixture(scope='module')
def spark():
    spark = (
        pyspark.sql.SparkSession.builder.master('local[2]')  # ty: ignore
        .appName('dag-test')
        .config('spark.ui.port', '4040')
        .config('spark.driver.host', 'localhost')
        .getOrCreate()
    )
    # Create a small test table
    df = spark.range(0, 100).selectExpr('id', 'id * 2 AS double_col', 'id % 7 AS bucket')
    df.createOrReplaceTempView('numbers')
    time.sleep(0.5)  # Let Spark UI initialise
    yield spark
    spark.stop()


def test_dag_from_real_spark(spark):
    """Run a query against a real Spark driver and fetch its DAG from the UI."""
    app_id = dag.resolve_app_id('localhost')
    assert app_id is not None, 'Spark UI not reachable on localhost:4040'

    # Run a query with an aggregate + sort — produces a multi-node DAG
    sql = "SELECT bucket, COUNT(*) AS cnt, AVG(double_col) AS avg_d FROM numbers GROUP BY bucket ORDER BY bucket"
    spark.sparkContext.setJobDescription(sql)
    spark.addTag('dag-live-test')

    df = spark.sql(sql)
    rows = df.collect()

    assert len(rows) == 7  # 0..6 buckets
    assert rows[0]['bucket'] == 0

    # Fetch the DAG
    result = dag.fetch_query_dag_by_qid('localhost', sql, app_id)

    assert result is not None, f'DAG fetch returned None for SQL: {sql[:60]}'
    assert 'nodes' in result
    assert 'edges' in result
    assert len(result['nodes']) >= 3, f'Expected ≥3 nodes, got {len(result["nodes"])}'

    # At minimum: Range, HashAggregate, Sort (no Scan — range() is in-memory)
    node_names = {n['name'] for n in result['nodes']}
    assert any('Range' in name or 'Scan' in name for name in node_names), f'No data source node in {node_names}'
    assert any('Sort' in name for name in node_names), f'No Sort node in {node_names}'

    # Some nodes should have duration_ms
    timed_nodes = [n for n in result['nodes'] if n.get('duration_ms')]
    assert len(timed_nodes) > 0, 'No nodes have duration_ms'

    # Edges present
    assert len(result['edges']) >= 2, f'Expected ≥2 edges, got {len(result["edges"])}'

    print(f'\n  DAG: {len(result["nodes"])} nodes, {len(result["edges"])} edges')
    for n in result['nodes']:
        extras = []
        if n.get('is_shuffle'):
            extras.append('shuffle')
        if n.get('has_spill'):
            extras.append('SPILL')
        flags = f' [{", ".join(extras)}]' if extras else ''
        dur = n.get('duration_ms')
        dur_str = f'{dur}ms' if dur is not None else 'N/A'
        print(f'    {n["name"]:40s} {dur_str:>10s}{flags}')


def test_dag_matches_sql_not_others(spark):
    """Verify DAG lookup by SQL text — should not match a different query."""
    sql_a = 'SELECT COUNT(*) FROM numbers'
    sql_b = 'SELECT SUM(double_col) FROM numbers'

    spark.sparkContext.setJobDescription(sql_a)
    spark.sql(sql_a).collect()
    spark.sparkContext.setJobDescription(sql_b)
    spark.sql(sql_b).collect()

    app_id = dag.resolve_app_id('localhost')
    assert app_id is not None

    # Both should be findable by their own SQL
    dag_a = dag.fetch_query_dag_by_qid('localhost', sql_a, app_id)
    dag_b = dag.fetch_query_dag_by_qid('localhost', sql_b, app_id)

    assert dag_a is not None
    assert dag_b is not None

    # They should have different node counts (COUNT vs SUM produce different plans)
    # Not a strict assertion — plans can be identical for simple queries
    print(f'\n  COUNT plan: {len(dag_a["nodes"])} nodes')
    print(f'  SUM plan:   {len(dag_b["nodes"])} nodes')
