"""Flashpoint gateway — EC2 control plane (Kindle #10/#12/#11).

Sessions are persisted to DynamoDB; the in-memory dict is a cache rebuilt
from DynamoDB + live ECS state on startup. Executors run on Fargate Spot;
the driver runs on-demand so Spot reclamation never kills the whole warehouse.
"""
import hashlib
import time
import logging
from collections import deque
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import store
import dag
import ecs_tasks
import spark_client
import reconcile as _reconcile_mod
from config import (
    CLUSTER, GRPC_PORT, WAREHOUSE_TTL_S, MAX_WAREHOUSES, SIZES,
)
from models import (
    CreateWarehouseRequest, WarehouseResponse, QueryRequest, ResizeRequest,
    QueryResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

warehouses: dict[str, dict] = {}
query_history: deque[dict] = deque(maxlen=500)


def _query_id(sql: str) -> str:
    normalized = " ".join(sql.strip().lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _fetch_query_dag(warehouse: dict, before_ids: set[int]) -> dict | None:
    return dag.fetch_query_dag(warehouse, before_ids)


def _sql_execution_ids(warehouse: dict) -> set[int]:
    return dag.sql_execution_ids(warehouse)


# --- App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup + shutdown lifecycle for the FastAPI server.

    Startup (before first request):
      1. Reconcile — rebuild in-memory warehouse state from DynamoDB.
         Running ECS tasks are restored; dead ones are cleaned up.
      2. Reaper — launch a background task that stops idle warehouses every 60s.
         This is the Snowflake model: you don't pay for idle compute.

    Shutdown (on server stop):
      Cancel the reaper.

    The FastAPI app holds no state between these two moments — all warehouse
    state lives in the in-memory dict (backed by DynamoDB) and the reaper task.
    """
    log.info("Flashpoint gateway starting (cluster=%s, ttl=%ds)", CLUSTER, WAREHOUSE_TTL_S)
    _reconcile_mod.reconcile(warehouses, CLUSTER, WAREHOUSE_TTL_S)
    reaper = asyncio.create_task(
        _reconcile_mod.reap_idle_warehouses(warehouses, spark_client, WAREHOUSE_TTL_S, CLUSTER)
    )
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


# --- Routes ---

@app.post("/warehouses", response_model=WarehouseResponse, status_code=201)
def create_warehouse(req: CreateWarehouseRequest):
    if req.size not in SIZES:
        raise HTTPException(status_code=400, detail=f"unknown size {req.size!r}")
    if req.name in warehouses:
        raise HTTPException(status_code=409, detail=f"warehouse {req.name!r} already exists")
    if len(warehouses) >= MAX_WAREHOUSES:
        raise HTTPException(status_code=429, detail=f"warehouse cap reached ({MAX_WAREHOUSES} max)")
    name = req.name
    executor_count = SIZES[req.size]
    log.info("Creating warehouse %s (size=%s, executors=%d)", name, req.size, executor_count)

    task_arn = ecs_tasks.run_driver_task()
    log.info("Driver task launched: %s", task_arn)

    ecs_tasks.wait_running(task_arn)
    task_ip = ecs_tasks.private_ip(task_arn)
    master_url = f"spark://{task_ip}:7077"
    endpoint = f"sc://{task_ip}:{GRPC_PORT}"
    log.info("Driver ready — master=%s endpoint=%s", master_url, endpoint)

    executor_arns = ecs_tasks.run_executor_tasks(master_url, executor_count)
    log.info("Launched %d executor tasks (Spot): %s", len(executor_arns), executor_arns)

    record = {
        "task_arn": task_arn,
        "executor_arns": executor_arns,
        "task_ip": task_ip,
        "endpoint": endpoint,
        "status": "running",
        "size": req.size,
        "executor_count": executor_count,
        "created_at": time.time(),
    }
    store.put_warehouse(name, record)
    warehouses[name] = record
    return WarehouseResponse(
        name=name, task_arn=task_arn, endpoint=endpoint,
        status="running", size=req.size, executor_count=executor_count,
    )


@app.get("/warehouses/{name}", response_model=WarehouseResponse)
def get_warehouse(name: str):
    s = warehouses.get(name)
    if not s:
        raise HTTPException(status_code=404, detail="warehouse not found")
    task_arn = s["task_arn"]
    status = "running" if (task_arn and ecs_tasks.is_running(task_arn)) else s["status"]
    return WarehouseResponse(
        name=name,
        task_arn=task_arn or None,
        endpoint=s.get("endpoint"),
        status=status,
        size=s["size"],
        executor_count=s["executor_count"],
    )


@app.get("/warehouses")
def list_warehouses_endpoint():
    items = []
    for name, s in warehouses.items():
        task_arn = s["task_arn"]
        status = "running" if (task_arn and ecs_tasks.is_running(task_arn)) else s.get("status", "suspended")
        items.append({
            "name": name,
            "status": status,
            "size": s["size"],
            "executor_count": s["executor_count"],
        })
    return {"warehouses": items, "count": len(items)}


@app.post("/warehouses/{name}/query", response_model=QueryResponse)
def run_query(name: str, req: QueryRequest):
    s = warehouses.get(name)
    if not s:
        raise HTTPException(status_code=404, detail="warehouse not found")
    if s["status"] != "running" or not ecs_tasks.is_running(s["task_arn"]):
        raise HTTPException(status_code=409, detail="warehouse not running")

    spark = spark_client.get(s["endpoint"], name)
    before_ids = _sql_execution_ids(s)
    t0 = time.time()
    try:
        df = spark.sql(req.sql)
        collected = df.collect()
    except Exception as exc:
        qid = _query_id(req.sql)
        query_history.append({
            "query_id": qid, "sql": req.sql, "status": "failed",
            "duration_ms": int((time.time() - t0) * 1000), "row_count": 0,
            "name": name, "ts": time.strftime("%H:%M:%S", time.localtime()),
        })
        raise HTTPException(status_code=400, detail=str(exc))

    qid = _query_id(req.sql)
    duration_ms = int((time.time() - t0) * 1000)
    columns = df.columns
    rows = [[str(v) for v in row] for row in collected]
    profile = _fetch_query_dag(s, before_ids)
    query_history.append({
        "query_id": qid, "sql": req.sql, "status": "success",
        "duration_ms": duration_ms, "row_count": len(rows),
        "name": name, "ts": time.strftime("%H:%M:%S", time.localtime()),
        "profile": profile,
    })
    log.info("Query %s on warehouse %s: %dms, %d rows\n%s", qid, name, duration_ms, len(rows), req.sql)
    return QueryResponse(
        query_id=qid,
        columns=columns,
        rows=rows,
        duration_ms=duration_ms,
        row_count=len(rows),
        profile=profile,
    )


@app.delete("/warehouses/{name}", status_code=204)
def delete_warehouse(name: str):
    s = warehouses.pop(name, None)
    if not s:
        raise HTTPException(status_code=404, detail="warehouse not found")
    spark_client.drop(name)
    ecs_tasks.stop_tasks(s)
    store.delete_warehouse(name)
    log.info("Deleted warehouse %s (driver + %d executors stopped)", name, len(s["executor_arns"]))


@app.post("/warehouses/{name}/suspend", status_code=200)
def suspend_warehouse(name: str):
    s = warehouses.get(name)
    if not s:
        raise HTTPException(status_code=404, detail="warehouse not found")
    if s["status"] == "suspended":
        return {"status": "suspended"}
    spark_client.drop(name)
    ecs_tasks.stop_tasks(s)
    warehouses[name] = {**s, "task_arn": None, "executor_arns": [], "task_ip": None, "status": "suspended"}
    store.update_warehouse_status(name, "suspended", task_arn=None, executor_arns=[], task_ip=None)
    log.info("Suspended warehouse %s", name)
    return {"status": "suspended"}


@app.post("/warehouses/{name}/resume", status_code=200, response_model=WarehouseResponse)
def resume_warehouse(name: str):
    s = warehouses.get(name)
    if not s:
        raise HTTPException(status_code=404, detail="warehouse not found")
    if s["status"] == "running":
        return WarehouseResponse(
            name=name, task_arn=s["task_arn"],
            endpoint=s.get("endpoint"), status="running",
            size=s["size"], executor_count=s["executor_count"],
        )

    size = s["size"]
    executor_count = SIZES[size]
    log.info("Resuming warehouse %s (size=%s)", name, size)

    task_arn = ecs_tasks.run_driver_task()
    ecs_tasks.wait_running(task_arn)
    task_ip = ecs_tasks.private_ip(task_arn)
    master_url = f"spark://{task_ip}:7077"
    endpoint = f"sc://{task_ip}:{GRPC_PORT}"
    executor_arns = ecs_tasks.run_executor_tasks(master_url, executor_count)

    update = {
        "task_arn": task_arn, "executor_arns": executor_arns,
        "task_ip": task_ip, "endpoint": endpoint,
        "executor_count": executor_count,
    }
    warehouses[name] = {**s, **update, "status": "running"}
    store.update_warehouse_status(name, "running", **update)
    log.info("Resumed warehouse %s → driver %s", name, task_arn)
    return WarehouseResponse(
        name=name, task_arn=task_arn, endpoint=endpoint,
        status="running", size=size, executor_count=executor_count,
    )


@app.post("/warehouses/{name}/resize", status_code=200, response_model=WarehouseResponse)
def resize_warehouse(name: str, req: ResizeRequest):
    s = warehouses.get(name)
    if not s:
        raise HTTPException(status_code=404, detail="warehouse not found")
    if s["status"] != "running":
        raise HTTPException(status_code=409, detail="warehouse is not running")
    if req.size not in SIZES:
        raise HTTPException(status_code=400, detail=f"unknown size {req.size!r}")

    new_count = SIZES[req.size]
    current_count = s["executor_count"]
    executor_arns: list[str] = list(s["executor_arns"])
    master_url = f"spark://{s['task_ip']}:7077"

    if new_count > current_count:
        delta = new_count - current_count
        new_arns = ecs_tasks.run_executor_tasks(master_url, delta)
        executor_arns.extend(new_arns)
        log.info("Scaled warehouse %s up: +%d executors (Spot)", name, delta)
    elif new_count < current_count:
        delta = current_count - new_count
        to_stop = executor_arns[-delta:]
        executor_arns = executor_arns[:-delta]
        for arn in to_stop:
            try:
                ecs_tasks.ecs.stop_task(cluster=CLUSTER, task=arn)
            except Exception as exc:
                log.error("Failed to stop executor %s during resize: %s", arn, exc)
        log.info("Scaled warehouse %s down: -%d executors", name, delta)

    warehouses[name] = {**s, "size": req.size, "executor_count": new_count, "executor_arns": executor_arns}
    store.update_warehouse_status(name, "running", size=req.size, executor_count=new_count, executor_arns=executor_arns)
    return WarehouseResponse(
        name=name, task_arn=s["task_arn"], endpoint=s["endpoint"],
        status="running", size=req.size, executor_count=new_count,
    )


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
    return {
        "status": "ok",
        "warehouses": len(warehouses),
        "sessions_table": store._TABLE_NAME,
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, log_level="info")
