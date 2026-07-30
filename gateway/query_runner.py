"""Background async query execution — Spark → Parquet → S3 → DDB."""

import logging
import time

import boto3

import spark_client
import store
from config import QUERY_RESULTS_BUCKET, REGION
from state import QueryStatus

log = logging.getLogger(__name__)
s3 = boto3.client('s3', region_name=REGION)


def run_async_query(qid: str, warehouse_name: str, sql: str) -> None:
    """Execute SQL, write result as Parquet to S3, update DDB status."""
    try:
        s = store.get_warehouse(warehouse_name)
        if not s or s['status'] != 'running':
            store.update_query_status(qid, QueryStatus.FAILED, error='warehouse not running')
            return

        spark = spark_client.get(s['endpoint'], warehouse_name)
        spark.addTag(qid)
        store.update_query_status(qid, QueryStatus.RUNNING)

        t0 = time.time()
        df = spark.sql(sql)
        s3_key = f'queries/{qid}/'

        df.coalesce(1).write.mode('overwrite').parquet(f's3a://{QUERY_RESULTS_BUCKET}/{s3_key}')

        duration_ms = int((time.time() - t0) * 1000)
        row_count = df.count()
        store.update_query_status(
            qid,
            QueryStatus.DONE,
            s3_key=s3_key,
            row_count=row_count,
            duration_ms=duration_ms,
        )
        log.info('Async query %s done: %d rows, %dms', qid, row_count, duration_ms)

    except Exception as exc:
        log.error('Async query %s failed: %s', qid, exc)
        store.update_query_status(qid, QueryStatus.FAILED, error=str(exc)[:1000])
