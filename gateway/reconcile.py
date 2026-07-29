"""Startup reconciliation and idle warehouse reaping.

State lives in DynamoDB, not in memory. The gateway has no local cache to
rebuild — reconcile() cleans up orphaned ECS tasks (Fargate containers
running with no DDB record). reap_idle_warehouses() queries DDB directly.

The reaper runs every 60s, stopping warehouses that exceed their TTL.
This is the Snowflake model: you don't pay for idle compute.
"""
import asyncio
import time
import logging
import ecs_tasks
import store

log = logging.getLogger(__name__)


def reconcile(cluster: str) -> None:
    """Clean up orphaned ECS tasks on gateway startup.

    Three cases:
      1. Live ECS task + DDB record exists → nothing to do (normal)
      2. DDB record says running + driver ECS task is dead → suspend it in DDB,
         kill leftover executor tasks
      3. Live ECS task + no DDB record → orphan, stop it immediately
    """
    try:
        db_warehouses = store.list_warehouses()
        db_arns: set[str] = set()
        for record in db_warehouses:
            task_arn = record.get("task_arn")
            if task_arn:
                db_arns.add(task_arn)
            for arn in (record.get("executor_arns") or []):
                db_arns.add(arn)

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


async def reap_idle_warehouses(spark_client, warehouse_ttl_s: int, cluster: str):
    """Background task — stops warehouses that have been idle too long.

    Queries DynamoDB every 60s for running warehouses. Suspends any that
    exceed the TTL by stopping their Fargate tasks and updating DDB.
    """
    while True:
        await asyncio.sleep(60)
        now = time.time()
        try:
            all_wh = store.list_warehouses()
        except Exception as exc:
            log.error("Could not list warehouses for reaping: %s", exc)
            continue

        for record in all_wh:
            if record.get("status") != "running":
                continue
            wid = record["name"]
            if now - record.get("created_at", now) > warehouse_ttl_s:
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
