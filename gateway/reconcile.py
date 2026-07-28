"""Startup reconciliation and idle session reaping."""
import asyncio
import time
import logging
import ecs_tasks
import store

log = logging.getLogger(__name__)


def reconcile(sessions: dict, cluster: str, session_ttl_s: int) -> None:
    """Rebuild in-memory session cache from DynamoDB + live ECS state."""
    try:
        db_sessions = store.list_sessions()
        db_arns = {
            arn
            for s in db_sessions
            for arn in ([s.get("task_arn")] if s.get("task_arn") else [])
            + (s.get("executor_arns") or [])
        }

        live_arns: set[str] = set()
        try:
            paginator = ecs_tasks.ecs.get_paginator("list_tasks")
            for page in paginator.paginate(cluster=cluster, desiredStatus="RUNNING"):
                live_arns.update(page.get("taskArns", []))
        except Exception as exc:
            log.error("Could not list ECS tasks during reconcile: %s", exc)

        for s in db_sessions:
            sid = s["session_id"]
            task_arn = s.get("task_arn", "")
            status = s.get("status", "running")

            if status == "suspended":
                continue

            if task_arn and task_arn in live_arns:
                sessions[sid] = s
                log.info("Reconciled session %s (driver live)", sid)
            else:
                log.warning("Session %s driver gone — suspending", sid)
                executor_arns = s.get("executor_arns") or []
                for arn in executor_arns:
                    if arn in live_arns:
                        try:
                            ecs_tasks.ecs.stop_task(cluster=cluster, task=arn, reason="orphan-executor")
                        except Exception as exc:
                            log.error("Failed to stop orphan executor %s: %s", arn, exc)
                store.update_session_status(
                    sid, "suspended", task_arn=None, executor_arns=[], task_ip=None
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


async def reap_idle_sessions(sessions: dict, spark_client, session_ttl_s: int, cluster: str):
    """Background task: stop sessions that exceed the TTL."""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        expired = [
            sid for sid, s in list(sessions.items())
            if now - s.get("created_at", now) > session_ttl_s
        ]
        for sid in expired:
            s = sessions.pop(sid, None)
            if s:
                log.warning("Reaping idle session %s (TTL exceeded)", sid)
                spark_client.drop(sid)
                for arn in ([s["task_arn"]] if s.get("task_arn") else []) + (s.get("executor_arns") or []):
                    try:
                        ecs_tasks.ecs.stop_task(cluster=cluster, task=arn)
                    except Exception as exc:
                        log.error("Failed to stop task %s: %s", arn, exc)
                try:
                    store.update_session_status(
                        sid, "suspended", task_arn=None, executor_arns=[], task_ip=None
                    )
                except Exception as exc:
                    log.error("Failed to update reaped session %s in DynamoDB: %s", sid, exc)
