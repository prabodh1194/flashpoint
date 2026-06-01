"""Flashpoint gateway — minimal EC2 control plane (Ember #24).

Launches Fargate driver tasks on demand and returns their gRPC endpoints.
In-memory session map only; persistence and HA deferred to Kindle #8/#10.
"""
import os
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
CLUSTER        = os.environ["FLASHPOINT_ECS_CLUSTER"]
TASK_DEF       = os.environ["FLASHPOINT_DRIVER_TASK_DEF"]
SUBNETS        = os.environ["FLASHPOINT_SUBNETS"].split(",")
SECURITY_GROUP = os.environ["FLASHPOINT_SECURITY_GROUP"]
REGION         = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
GRPC_PORT      = int(os.environ.get("FLASHPOINT_GRPC_PORT", "15002"))

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


def _public_ip(task_arn: str) -> str:
    resp = ecs.describe_tasks(cluster=CLUSTER, tasks=[task_arn])
    eni_id = next(
        d["value"]
        for d in resp["tasks"][0]["attachments"][0]["details"]
        if d["name"] == "networkInterfaceId"
    )
    iface = ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
    return iface["NetworkInterfaces"][0]["Association"]["PublicIp"]


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

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Flashpoint gateway starting (cluster=%s)", CLUSTER)
    yield
    log.info("Flashpoint gateway shutting down")


app = FastAPI(title="Flashpoint Gateway", lifespan=lifespan)


@app.post("/sessions", response_model=SessionResponse, status_code=201)
def create_session():
    """Launch a Fargate driver task and return its gRPC endpoint."""
    session_id = str(uuid.uuid4())
    log.info("Creating session %s", session_id)

    task_arn = _run_driver_task()
    log.info("Task launched: %s", task_arn)

    _wait_running(task_arn)
    ip = _public_ip(task_arn)
    endpoint = f"sc://{ip}:{GRPC_PORT}"
    log.info("Session %s ready at %s", session_id, endpoint)

    sessions[session_id] = {
        "task_arn": task_arn,
        "task_ip": ip,
        "endpoint": endpoint,
        "status": "running",
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
    ecs.stop_task(cluster=CLUSTER, task=s["task_arn"])
    log.info("Stopped task %s (session %s)", s["task_arn"], session_id)


@app.get("/healthz")
def health():
    return {"status": "ok", "sessions": len(sessions)}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, log_level="info")
