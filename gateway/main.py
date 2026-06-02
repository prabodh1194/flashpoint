"""Flashpoint gateway — minimal EC2 control plane (Ember #24).

Launches Fargate driver tasks on demand and returns their gRPC endpoints.
In-memory session map only; persistence and HA deferred to Kindle #8/#10.
"""
import asyncio
import hashlib
import json
import os
import re
import time
import uuid
import logging
import urllib.request
from collections import deque
from contextlib import asynccontextmanager

import boto3
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pyspark.sql import SparkSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# --- Config (env vars set on the EC2 gateway host) ---
CLUSTER          = os.environ["FLASHPOINT_ECS_CLUSTER"]
TASK_DEF         = os.environ["FLASHPOINT_DRIVER_TASK_DEF"]
EXECUTOR_TASK_DEF = os.environ["FLASHPOINT_EXECUTOR_TASK_DEF"]
SUBNETS          = os.environ["FLASHPOINT_SUBNETS"].split(",")
SECURITY_GROUP   = os.environ["FLASHPOINT_SECURITY_GROUP"]
REGION           = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
GRPC_PORT        = int(os.environ.get("FLASHPOINT_GRPC_PORT", "15002"))
EXECUTOR_COUNT   = int(os.environ.get("FLASHPOINT_EXECUTOR_COUNT", "2"))
# Stop idle tasks after this many seconds to prevent runaway Fargate cost
SESSION_TTL_S    = int(os.environ.get("FLASHPOINT_SESSION_TTL_S", str(2 * 3600)))
MAX_SESSIONS     = int(os.environ.get("FLASHPOINT_MAX_SESSIONS", "3"))
# Spark driver UI / SQL REST API port — source of query-profile DAGs (Beacon #19)
SPARK_UI_PORT    = int(os.environ.get("FLASHPOINT_SPARK_UI_PORT", "4040"))

ecs = boto3.client("ecs", region_name=REGION)

# In-memory session store: session_id -> {task_arn, executor_arns, task_ip, endpoint, ...}
sessions: dict[str, dict] = {}

# Query history: capped deque of completed query records
query_history: deque[dict] = deque(maxlen=500)


# --- Helpers ---

def _run_driver_task() -> str:
    resp = ecs.run_task(
        cluster=CLUSTER,
        taskDefinition=TASK_DEF,
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": SUBNETS,
                "securityGroups": [SECURITY_GROUP],
                "assignPublicIp": "ENABLED",
            }
        },
    )
    failures = resp.get("failures", [])
    if failures:
        raise RuntimeError(f"RunTask failed: {failures}")
    return resp["tasks"][0]["taskArn"]


def _wait_running(task_arn: str) -> None:
    waiter = ecs.get_waiter("tasks_running")
    waiter.wait(cluster=CLUSTER, tasks=[task_arn])


def _private_ip(task_arn: str) -> str:
    """Read private IP directly from ECS task attachment details — no ENI call needed."""
    resp = ecs.describe_tasks(cluster=CLUSTER, tasks=[task_arn])
    details = resp["tasks"][0]["attachments"][0]["details"]
    return next(d["value"] for d in details if d["name"] == "privateIPv4Address")


def _run_executor_tasks(master_url: str, n: int) -> list[str]:
    """Launch N Fargate Spot executor workers pointing at the driver's master URL."""
    arns = []
    for _ in range(n):
        resp = ecs.run_task(
            cluster=CLUSTER,
            taskDefinition=EXECUTOR_TASK_DEF,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": SUBNETS,
                    "securityGroups": [SECURITY_GROUP],
                    "assignPublicIp": "ENABLED",
                }
            },
            overrides={
                "containerOverrides": [{
                    "name": "spark-executor",
                    "environment": [
                        {"name": "SPARK_MASTER_URL", "value": master_url}
                    ],
                }]
            },
        )
        failures = resp.get("failures", [])
        if failures:
            log.error("Executor RunTask failed: %s", failures)
            continue
        arns.append(resp["tasks"][0]["taskArn"])
    return arns


def _is_running(task_arn: str) -> bool:
    resp = ecs.describe_tasks(cluster=CLUSTER, tasks=[task_arn])
    tasks = resp.get("tasks", [])
    return bool(tasks) and tasks[0].get("lastStatus") == "RUNNING"


def _query_id(sql: str) -> str:
    """Stable 16-char hex ID derived from normalized SQL content."""
    normalized = " ".join(sql.strip().lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


# --- Query-profile DAG via the Spark driver UI REST API (Beacon #19) ---
#
# The Spark UI exposes per-query execution plans at
# /api/v1/applications/{appId}/sql/{executionId}?details=true, returning operator
# nodes, parent-child edges, and per-node metrics. We fetch this best-effort after
# a query runs; any failure leaves the query result untouched (profile = None).

_DURATION_UNITS_MS = {"ms": 1.0, "s": 1000.0, "m": 60_000.0, "min": 60_000.0, "h": 3_600_000.0}


def _ui_get(driver_ip: str, path: str, timeout: float = 2.0):
    """GET http://{driver_ip}:{SPARK_UI_PORT}/api/v1{path} and parse JSON."""
    url = f"http://{driver_ip}:{SPARK_UI_PORT}/api/v1{path}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _resolve_app_id(driver_ip: str) -> str | None:
    """Return the running application's id (SparkConnectServer hosts exactly one)."""
    apps = _ui_get(driver_ip, "/applications")
    if not apps:
        return None
    running = [a for a in apps if any(not at.get("completed", True) for at in a.get("attempts", []))]
    return (running or apps)[0]["id"]


def _metric_total(value: str) -> str:
    """Spark metric values may be 'total (min, med, max ...)\\nN unit (...)'.
    Return the human total — the leading token of the last line."""
    last = value.strip().splitlines()[-1].strip()
    return last


def _parse_duration_ms(value: str) -> int | None:
    """Parse a Spark duration metric string like '390 ms' or the total line of an
    aggregated metric into milliseconds. Returns None if unparseable."""
    m = re.match(r"([\d,.]+)\s*(ms|min|s|m|h)\b", _metric_total(value))
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    return int(num * _DURATION_UNITS_MS.get(m.group(2), 1.0))


def _is_nonzero_size(value: str) -> bool:
    """True if a Spark size metric ('0.0 B', '512.0 KiB') is greater than zero."""
    m = re.match(r"([\d,.]+)", _metric_total(value))
    return bool(m) and float(m.group(1).replace(",", "")) > 0


def _transform_dag(detail: dict) -> dict:
    """Map a raw Spark SQL execution detail into the compact UI schema."""
    nodes = []
    shuffle_node_ids = set()
    for n in detail.get("nodes", []):
        metrics = {m["name"]: m["value"] for m in n.get("metrics", [])}
        name = n.get("nodeName", "")

        is_shuffle = (
            "Exchange" in name
            or "Shuffle" in name
            or "shuffle bytes written" in metrics
        )
        if is_shuffle:
            shuffle_node_ids.add(n["nodeId"])

        has_spill = "spill size" in metrics and _is_nonzero_size(metrics["spill size"])

        duration_ms = None
        for key in ("duration", "sort time", "time in aggregation build"):
            if key in metrics:
                duration_ms = _parse_duration_ms(metrics[key])
                if duration_ms is not None:
                    break

        nodes.append({
            "id": n["nodeId"],
            "name": name,
            "duration_ms": duration_ms,
            "metrics": {k: _metric_total(v) for k, v in metrics.items()},
            "is_shuffle": is_shuffle,
            "has_skew": False,  # conservative: only set when an explicit skew metric exists
            "has_spill": has_spill,
        })

    edges = [
        {"from": e["fromId"], "to": e["toId"], "is_shuffle": e["fromId"] in shuffle_node_ids}
        for e in detail.get("edges", [])
    ]
    return {"nodes": nodes, "edges": edges}


def _fetch_query_dag(session: dict, before_ids: set[int]) -> dict | None:
    """Best-effort: fetch the just-run query's execution DAG from the driver UI.

    Polls the SQL execution list for a new COMPLETED execution (one not present
    before the query ran), then fetches and transforms its detail. Returns None
    on any failure so the query result is never affected.
    """
    driver_ip = session["task_ip"]
    try:
        app_id = session.get("app_id") or _resolve_app_id(driver_ip)
        if not app_id:
            return None
        session["app_id"] = app_id

        deadline = time.time() + 1.5
        while time.time() < deadline:
            execs = _ui_get(driver_ip, f"/applications/{app_id}/sql?details=false")
            new = [e for e in execs if e["id"] not in before_ids and e.get("status") == "COMPLETED"]
            if new:
                exec_id = max(e["id"] for e in new)
                detail = _ui_get(driver_ip, f"/applications/{app_id}/sql/{exec_id}?details=true")
                if detail.get("nodes"):
                    return _transform_dag(detail)
            time.sleep(0.15)
    except Exception as exc:
        log.warning("Query DAG fetch failed for driver %s: %s", driver_ip, exc)
    return None


def _sql_execution_ids(session: dict) -> set[int]:
    """Best-effort snapshot of existing SQL execution ids before a query runs."""
    try:
        app_id = session.get("app_id") or _resolve_app_id(session["task_ip"])
        if not app_id:
            return set()
        session["app_id"] = app_id
        execs = _ui_get(session["task_ip"], f"/applications/{app_id}/sql?details=false")
        return {e["id"] for e in execs}
    except Exception:
        return set()


def _stop_orphaned_tasks() -> None:
    """On startup: stop any ECS tasks that are not tracked in the sessions map."""
    known_arns = {
        arn
        for s in sessions.values()
        for arn in [s["task_arn"]] + s.get("executor_arns", [])
    }
    try:
        paginator = ecs.get_paginator("list_tasks")
        for page in paginator.paginate(cluster=CLUSTER, desiredStatus="RUNNING"):
            for arn in page.get("taskArns", []):
                if arn not in known_arns:
                    log.warning("Stopping orphaned task %s", arn)
                    try:
                        ecs.stop_task(cluster=CLUSTER, task=arn, reason="orphan-cleanup")
                    except Exception as exc:
                        log.error("Failed to stop orphan %s: %s", arn, exc)
    except Exception as exc:
        log.error("Orphan cleanup failed: %s", exc)


# --- API models ---

class SessionResponse(BaseModel):
    session_id: str
    task_arn: str
    endpoint: str
    status: str


class QueryRequest(BaseModel):
    sql: str


class DagNode(BaseModel):
    id: int
    name: str
    duration_ms: int | None = None
    metrics: dict[str, str] = {}
    is_shuffle: bool = False
    has_skew: bool = False
    has_spill: bool = False


class DagEdge(BaseModel):
    from_: int = Field(alias="from")
    to: int
    is_shuffle: bool = False

    model_config = {"populate_by_name": True}


class QueryProfile(BaseModel):
    nodes: list[DagNode]
    edges: list[DagEdge]


class QueryResponse(BaseModel):
    query_id: str
    columns: list[str]
    rows: list[list]
    duration_ms: int
    row_count: int
    profile: QueryProfile | None = None


# --- App ---

async def _reap_idle_sessions():
    """Stop Fargate tasks that have exceeded SESSION_TTL_S to prevent runaway cost."""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        expired = [
            sid for sid, s in list(sessions.items())
            if now - s.get("created_at", now) > SESSION_TTL_S
        ]
        for sid in expired:
            s = sessions.pop(sid, None)
            if s:
                log.warning("Reaping idle session %s", sid)
                _drop_spark(sid)
                for arn in [s["task_arn"]] + s.get("executor_arns", []):
                    try:
                        ecs.stop_task(cluster=CLUSTER, task=arn)
                    except Exception as exc:
                        log.error("Failed to stop task %s: %s", arn, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Flashpoint gateway starting (cluster=%s, ttl=%ds)", CLUSTER, SESSION_TTL_S)
    _stop_orphaned_tasks()
    reaper = asyncio.create_task(_reap_idle_sessions())
    yield
    reaper.cancel()
    log.info("Flashpoint gateway shutting down")


app = FastAPI(title="Flashpoint Gateway", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cache one SparkSession per session_id so we don't reconnect on every query
_spark_cache: dict[str, SparkSession] = {}


def _get_spark(session_id: str, endpoint: str) -> SparkSession:
    if session_id not in _spark_cache:
        _spark_cache[session_id] = (
            SparkSession.builder.remote(endpoint).getOrCreate()
        )
    return _spark_cache[session_id]


def _drop_spark(session_id: str) -> None:
    spark = _spark_cache.pop(session_id, None)
    if spark:
        try:
            spark.stop()
        except Exception:
            pass


@app.post("/sessions", response_model=SessionResponse, status_code=201)
def create_session():
    """Launch a Fargate driver task and return its gRPC endpoint."""
    if len(sessions) >= MAX_SESSIONS:
        raise HTTPException(status_code=429, detail=f"session cap reached ({MAX_SESSIONS} max)")
    session_id = str(uuid.uuid4())
    log.info("Creating session %s", session_id)

    task_arn = _run_driver_task()
    log.info("Driver task launched: %s", task_arn)

    _wait_running(task_arn)
    private_ip = _private_ip(task_arn)
    master_url = f"spark://{private_ip}:7077"
    endpoint = f"sc://{private_ip}:{GRPC_PORT}"
    log.info("Driver ready — master=%s endpoint=%s", master_url, endpoint)

    executor_arns = _run_executor_tasks(master_url, EXECUTOR_COUNT)
    log.info("Launched %d executor tasks: %s", len(executor_arns), executor_arns)

    sessions[session_id] = {
        "task_arn": task_arn,
        "executor_arns": executor_arns,
        "task_ip": private_ip,
        "endpoint": endpoint,
        "status": "running",
        "created_at": time.time(),
    }
    return SessionResponse(
        session_id=session_id, task_arn=task_arn, endpoint=endpoint, status="running"
    )


@app.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str):
    s = sessions.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    s["status"] = "running" if _is_running(s["task_arn"]) else "stopped"
    return SessionResponse(session_id=session_id, **s)


@app.get("/sessions")
def list_sessions():
    return {"sessions": list(sessions.keys()), "count": len(sessions)}


@app.post("/sessions/{session_id}/query", response_model=QueryResponse)
def run_query(session_id: str, req: QueryRequest):
    """Execute SQL against a running session's Spark Connect driver."""
    s = sessions.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    if not _is_running(s["task_arn"]):
        raise HTTPException(status_code=409, detail="session not running")

    spark = _get_spark(session_id, s["endpoint"])
    before_ids = _sql_execution_ids(s)  # best-effort snapshot for DAG correlation
    t0 = time.time()
    try:
        df = spark.sql(req.sql)
        collected = df.collect()
    except Exception as exc:
        qid = _query_id(req.sql)
        query_history.append({
            "query_id": qid, "sql": req.sql, "status": "failed",
            "duration_ms": int((time.time() - t0) * 1000), "row_count": 0,
            "session_id": session_id, "ts": time.strftime("%H:%M:%S", time.localtime()),
        })
        raise HTTPException(status_code=400, detail=str(exc))

    qid = _query_id(req.sql)
    duration_ms = int((time.time() - t0) * 1000)
    columns = df.columns
    rows = [[str(v) for v in row] for row in collected]
    profile = _fetch_query_dag(s, before_ids)  # best-effort; None on any failure
    query_history.append({
        "query_id": qid, "sql": req.sql, "status": "success",
        "duration_ms": duration_ms, "row_count": len(rows),
        "session_id": session_id, "ts": time.strftime("%H:%M:%S", time.localtime()),
        "profile": profile,
    })
    log.info("Query %s on session %s: %dms, %d rows\n%s", qid, session_id, duration_ms, len(rows), req.sql)
    return QueryResponse(
        query_id=qid,
        columns=columns,
        rows=rows,
        duration_ms=duration_ms,
        row_count=len(rows),
        profile=profile,
    )


@app.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    s = sessions.pop(session_id, None)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    _drop_spark(session_id)
    for arn in [s["task_arn"]] + s.get("executor_arns", []):
        try:
            ecs.stop_task(cluster=CLUSTER, task=arn)
        except Exception as exc:
            log.error("Failed to stop task %s: %s", arn, exc)
    log.info("Stopped driver + %d executors (session %s)", len(s.get("executor_arns", [])), session_id)


@app.get("/history")
def list_history():
    return {"history": list(query_history), "count": len(query_history)}


@app.get("/history/{query_id}")
def get_history_entry(query_id: str):
    entry = next((e for e in query_history if e["query_id"] == query_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail="query not found")
    return entry


@app.get("/healthz")
def health():
    return {"status": "ok", "sessions": len(sessions)}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, log_level="info")
