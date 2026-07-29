"""Query execution and history routes."""

import hashlib
import logging
import time

from fastapi import APIRouter, HTTPException

import dag
import ecs_tasks
import spark_client
import state
import store
from models import QueryRequest, QueryResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix='/warehouses', tags=['queries'])


def _query_id(sql: str) -> str:
    normalized = ' '.join(sql.strip().lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _fetch_query_dag(warehouse: dict, before_ids: set[int]) -> dict | None:
    return dag.fetch_query_dag(warehouse, before_ids)


def _sql_execution_ids(warehouse: dict) -> set[int]:
    return dag.sql_execution_ids(warehouse)


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
