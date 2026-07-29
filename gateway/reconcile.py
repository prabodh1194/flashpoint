"""Startup reconciliation and idle warehouse reaping.

The gateway keeps warehouse state in two places:
  - In-memory (fast, lost on gateway restart)
  - DynamoDB (durable, survives restarts)

When the gateway boots, memory is empty but DynamoDB has old records — and
real Fargate tasks may still be running, burning money with nobody tracking them.
Reconcile fixes this; see reconcile() below.

The reaper runs in the background every 60s, stopping warehouses that exceed
their TTL. This is the Snowflake model: you don't pay for idle compute.
"""
import asyncio
import time
import logging
import ecs_tasks
import store

log = logging.getLogger(__name__)


def reconcile(warehouses: dict, cluster: str, warehouse_ttl_s: int) -> None:
    """Rebuild the in-memory warehouse cache from DynamoDB + live ECS state.

    Runs once at gateway startup. Three outcomes per warehouse:

    1. Driver alive → restore to memory (normal case after gateway restart)
    2. Driver dead → mark "suspended" in DynamoDB, kill leftover executors
    3. Suspended → skip (no tasks should exist)

    Also cleans up orphaned ECS tasks — Fargate containers running with no
    corresponding DynamoDB record. These are runaway-cost bugs and must be killed.
    """
    try:
        db_warehouses = store.list_warehouses()
        db_arns = {
            arn
            for record in db_warehouses
            for arn in ([record.get("task_arn")] if record.get("task_arn") else [])
            + (record.get("executor_arns") or [])
        }

        live_arns: set[str] = set()
        try:
            paginator = ecs_tasks.ecs.get_paginator("list_tasks")
            for page in paginator.paginate(cluster=cluster, desiredStatus="RUNNING"):
                live_arns.update(page.get("taskArns", []))
        except Exception as exc:
            log.error("Could not list ECS tasks during reconcile: %s", exc)

        for record in db_warehouses:
            wid = record["name"]
            task_arn = record.get("task_arn", "")
            status = record.get("status", "running")

            if status == "suspended":
                continue

            if task_arn and task_arn in live_arns:
                warehouses[wid] = record
                log.info("Reconciled warehouse %s (driver live)", wid)
            else:
                log.warning("Warehouse %s driver gone — suspending", wid)
                executor_arns = record.get("executor_arns") or []
                for arn in executor_arns:
                    if arn in live_arns:
                        try:
                            ecs_tasks.ecs.stop_task(cluster=cluster, task=arn, reason="orphan-executor")
                        except Exception as exc:
                            log.error("Failed to stop orphan executor %s: %s", arn, exc)
                store.update_warehouse_status(
                    wid, "suspended", task_arn=None, executor_arns=[], task_ip=None
                )

        for arn in live_arns:
            if arn not in db_arns:
                log.warning("Stopping untracked orphan task %s", arn)
                try:
                    ecs_tasks.ecs.stop_task(cluster=cluster, task=arn, reason="orphan-cleanup")
                except Exception as exc:
                    log.error("Failed to stop orphan %s: %s", arn, exc)

    except Exception as exc:
        log.error("Reconcile failed: %s", exc)


async def reap_idle_warehouses(warehouses: dict, spark_client, warehouse_ttl_s: int, cluster: str):
    """Background task — stops warehouses that have been idle too long.

    Runs every 60s forever. For each warehouse in memory:
      - If created_at is older than warehouse_ttl_s (default 2 hours)
      - → drop the Spark Connect session
      - → stop all Fargate tasks (driver + executors)
      - → mark "suspended" in DynamoDB

    This is the Snowflake warehouse model: you don't pay for idle compute.
    The warehouse resumes on the next query (cold start).
    """
    while True:
        await asyncio.sleep(60)
        now = time.time()
        expired = [
            wid for wid, record in list(warehouses.items())
            if now - record.get("created_at", now) > warehouse_ttl_s
        ]
        for wid in expired:
            record = warehouses.pop(wid, None)
            if record:
                log.warning("Reaping idle warehouse %s (TTL exceeded)", wid)
                spark_client.drop(wid)
                for arn in ([record["task_arn"]] if record.get("task_arn") else []) + (record.get("executor_arns") or []):
                    try:
                        ecs_tasks.ecs.stop_task(cluster=cluster, task=arn)
                    except Exception as exc:
                        log.error("Failed to stop task %s: %s", arn, exc)
                try:
                    store.update_warehouse_status(
                        wid, "suspended", task_arn=None, executor_arns=[], task_ip=None
                    )
                except Exception as exc:
                    log.error("Failed to update reaped warehouse %s in DynamoDB: %s", wid, exc)
