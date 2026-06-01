"""Flashpoint gateway — minimal EC2 control plane (Ember #24).

Launches Fargate driver tasks on demand and returns their gRPC endpoints.
In-memory session map only; persistence and HA deferred to Kindle #8/#10.
"""
import asyncio
import os
import time
import uuid
import logging
from contextlib import asynccontextmanager

import boto3
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

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

ecs = boto3.client("ecs", region_name=REGION)
ec2 = boto3.client("ec2", region_name=REGION)

# In-memory session store: session_id -> {task_arn, task_ip, endpoint, status}
sessions: dict[str, dict] = {}


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


def _eni_id(task_arn: str) -> str:
    resp = ecs.describe_tasks(cluster=CLUSTER, tasks=[task_arn])
    return next(
        d["value"]
        for d in resp["tasks"][0]["attachments"][0]["details"]
        if d["name"] == "networkInterfaceId"
    )


def _public_ip(task_arn: str) -> str:
    iface = ec2.describe_network_interfaces(NetworkInterfaceIds=[_eni_id(task_arn)])
    return iface["NetworkInterfaces"][0]["Association"]["PublicIp"]


def _private_ip(task_arn: str) -> str:
    iface = ec2.describe_network_interfaces(NetworkInterfaceIds=[_eni_id(task_arn)])
    return iface["NetworkInterfaces"][0]["PrivateIpAddress"]


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


# --- API models ---

class SessionResponse(BaseModel):
    session_id: str
    task_arn: str
    endpoint: str
    status: str


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
                for arn in [s["task_arn"]] + s.get("executor_arns", []):
                    try:
                        ecs.stop_task(cluster=CLUSTER, task=arn)
                    except Exception as exc:
                        log.error("Failed to stop task %s: %s", arn, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Flashpoint gateway starting (cluster=%s, ttl=%ds)", CLUSTER, SESSION_TTL_S)
    reaper = asyncio.create_task(_reap_idle_sessions())
    yield
    reaper.cancel()
    log.info("Flashpoint gateway shutting down")


app = FastAPI(title="Flashpoint Gateway", lifespan=lifespan)


@app.post("/sessions", response_model=SessionResponse, status_code=201)
def create_session():
    """Launch a Fargate driver task and return its gRPC endpoint."""
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


@app.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    s = sessions.pop(session_id, None)
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    for arn in [s["task_arn"]] + s.get("executor_arns", []):
        try:
            ecs.stop_task(cluster=CLUSTER, task=arn)
        except Exception as exc:
            log.error("Failed to stop task %s: %s", arn, exc)
    log.info("Stopped driver + %d executors (session %s)", len(s.get("executor_arns", [])), session_id)


@app.get("/healthz")
def health():
    return {"status": "ok", "sessions": len(sessions)}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, log_level="info")
