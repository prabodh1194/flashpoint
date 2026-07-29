"""ECS task management helpers for the Flashpoint gateway."""
import logging
import boto3
from config import CLUSTER, TASK_DEF, EXECUTOR_TASK_DEF, SUBNETS, SECURITY_GROUP, REGION

log = logging.getLogger(__name__)

ecs = boto3.client("ecs", region_name=REGION)


def run_driver_task() -> str:
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


def wait_running(task_arn: str) -> None:
    waiter = ecs.get_waiter("tasks_running")
    waiter.wait(cluster=CLUSTER, tasks=[task_arn])


def private_ip(task_arn: str) -> str:
    resp = ecs.describe_tasks(cluster=CLUSTER, tasks=[task_arn])
    details = resp["tasks"][0]["attachments"][0]["details"]
    return next(d["value"] for d in details if d["name"] == "privateIPv4Address")


def run_executor_tasks(master_url: str, count: int) -> list[str]:
    arns = []
    for _ in range(count):
        resp = ecs.run_task(
            cluster=CLUSTER,
            taskDefinition=EXECUTOR_TASK_DEF,
            capacityProviderStrategy=[{"capacityProvider": "FARGATE_SPOT", "weight": 1}],
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


def is_running(task_arn: str) -> bool:
    resp = ecs.describe_tasks(cluster=CLUSTER, tasks=[task_arn])
    tasks = resp.get("tasks", [])
    return bool(tasks) and tasks[0].get("lastStatus") == "RUNNING"


def stop_tasks(warehouse_record: dict) -> None:
    task_arn = warehouse_record["task_arn"]
    executor_arns = warehouse_record["executor_arns"]
    for arn in ([task_arn] if task_arn else []) + executor_arns:
        try:
            ecs.stop_task(cluster=CLUSTER, task=arn)
        except Exception as exc:
            log.error("Failed to stop task %s: %s", arn, exc)
