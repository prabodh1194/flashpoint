"""Query execution and history routes."""

import hashlib
import logging
import threading
import time

import boto3
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

import dag
import ecs_tasks
import spark_client
import state
import store
from config import QUERY_RESULT_TTL_DAYS, QUERY_RESULTS_BUCKET, REGION
from models import QueryRequest, QueryResponse
from state import QueryStatus

log = logging.getLogger(__name__)
router = APIRouter(prefix='/warehouses', tags=['queries'])
queries_router = APIRouter(prefix='/queries', tags=['queries'])
s3 = boto3.client('s3', region_name=REGION)


# --- Helpers ---


def _query_id(sql: str) -> str:
    normalized = ' '.join(sql.strip().lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _async_query_id(sql: str, warehouse_name: str) -> str:
    """Stable ID: same (sql + warehouse snapshot) → same qid → cache hit."""
    wh = store.get_warehouse(warehouse_name)
    created = str(wh.get('created_at', '')) if wh else ''
    payload = ' '.join(sql.strip().lower().split()) + created
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _fetch_query_dag(warehouse: dict, before_ids: set[int]) -> dict | None:
    return dag.fetch_query_dag(warehouse, before_ids)


def _sql_execution_ids(warehouse: dict) -> set[int]:
    return dag.sql_execution_ids(warehouse)


# --- Sync query (unchanged) ---


@router.post('/{name}/query', response_model=QueryResponse)
def run_query(name: str, req: QueryRequest):
    s = store.get_warehouse(name)
    if not s:
        raise HTTPException(status_code=404, detail='warehouse not found')
    if s['status'] != 'running' or not ecs_tasks.is_running(s['task_arn']):
        raise HTTPException(status_code=409, detail='warehouse not running')

    spark = spark_client.get(s['endpoint'], name)
    before_ids = _sql_execution_ids(s)
    t0 = time.time()
    try:
        df = spark.sql(req.sql)
        collected = df.collect()
    except Exception as exc:
        qid = _query_id(req.sql)
        state.query_history.append(
            {
                'query_id': qid,
                'sql': req.sql,
                'status': 'failed',
                'duration_ms': int((time.time() - t0) * 1000),
                'row_count': 0,
                'name': name,
                'ts': time.strftime('%H:%M:%S', time.localtime()),
            }
        )
        raise HTTPException(status_code=400, detail=str(exc))

    qid = _query_id(req.sql)
    duration_ms = int((time.time() - t0) * 1000)
    columns = df.columns
    rows = [[str(v) for v in row] for row in collected]
    profile = _fetch_query_dag(s, before_ids)
    state.query_history.append(
        {
            'query_id': qid,
            'sql': req.sql,
            'status': 'success',
            'duration_ms': duration_ms,
            'row_count': len(rows),
            'name': name,
            'ts': time.strftime('%H:%M:%S', time.localtime()),
            'profile': profile,
        }
    )
    log.info(
        'Query %s on warehouse %s: %dms, %d rows\n%s',
        qid,
        name,
        duration_ms,
        len(rows),
        req.sql,
    )
    return QueryResponse(
        query_id=qid,
        columns=columns,
        rows=rows,
        duration_ms=duration_ms,
        row_count=len(rows),
        profile=profile,
    )


# --- Async query submit ---


@router.post('/{name}/query/async')
def run_query_async(name: str, req: QueryRequest):
    s = store.get_warehouse(name)
    if not s:
        raise HTTPException(status_code=404, detail='warehouse not found')
    if s['status'] != 'running' or not ecs_tasks.is_running(s['task_arn']):
        raise HTTPException(status_code=409, detail='warehouse not running')

    qid = _async_query_id(req.sql, name)
    existing = store.get_query_record(qid)
    if existing and existing.get('status') == QueryStatus.DONE:
        return {
            'query_id': qid,
            'status': QueryStatus.DONE,
            'row_count': existing.get('row_count'),
            'duration_ms': existing.get('duration_ms'),
        }
    if existing and existing.get('status') in (QueryStatus.QUEUED, QueryStatus.RUNNING):
        return {'query_id': qid, 'status': existing['status']}

    ttl = int(time.time()) + QUERY_RESULT_TTL_DAYS * 86400
    store.put_query_record(
        qid,
        {
            'warehouse_name': name,
            'sql': req.sql,
            'status': QueryStatus.QUEUED,
            'submitted_at': time.time(),
            'ttl': ttl,
        },
    )

    from query_runner import run_async_query

    thread = threading.Thread(target=run_async_query, args=(qid, name, req.sql), daemon=True)
    thread.start()

    return {'query_id': qid, 'status': QueryStatus.QUEUED}


# --- Cancel ---


@router.post('/{name}/query/cancel')
def cancel_query(name: str, qid: str | None = None):
    s = store.get_warehouse(name)
    if not s:
        raise HTTPException(status_code=404, detail='warehouse not found')

    spark_client.interrupt(name, qid)
    if qid:
        store.update_query_status(qid, QueryStatus.CANCELLED)
    return {'status': 'cancelled'}


# --- Poll status ---


@queries_router.get('/{query_id}')
def get_query_status(query_id: str):
    record = store.get_query_record(query_id)
    if not record:
        raise HTTPException(status_code=404, detail='query not found')
    return {
        'query_id': query_id,
        'status': record['status'],
        'row_count': record.get('row_count'),
        'duration_ms': record.get('duration_ms'),
        'submitted_at': record.get('submitted_at'),
    }


# --- Fetch materialized results ---


@queries_router.get('/{query_id}/result')
def get_query_result(query_id: str):
    record = store.get_query_record(query_id)
    if not record:
        raise HTTPException(status_code=404, detail='query not found')
    if record['status'] != QueryStatus.DONE:
        raise HTTPException(status_code=409, detail=f'query not done (status: {record["status"]})')
    s3_key = record.get('s3_key')
    if not s3_key:
        raise HTTPException(status_code=404, detail='no materialized result')

    url = s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': QUERY_RESULTS_BUCKET, 'Key': s3_key},
        ExpiresIn=900,
    )
    return RedirectResponse(url=url, status_code=302)


# --- History routes ---

history_router = APIRouter(prefix='/history', tags=['history'])


@history_router.get('')
def list_history():
    return {'history': list(state.query_history), 'count': len(state.query_history)}


@history_router.get('/{query_id}')
def get_history_entry(query_id: str):
    entry = next((e for e in state.query_history if e['query_id'] == query_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail='query not found')
    return entry
