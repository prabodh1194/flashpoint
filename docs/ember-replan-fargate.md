# Ember Milestone — Revised Plan (Fargate)

> Supersedes LMI-based plan. Date: 2026-06-01.

---

## What changed

Compute substrate: **Lambda Managed Instances → ECS Fargate**
See ADR-001 for the full reasoning.

The thesis is unchanged: multi-node Spark Connect on AWS, benchmarked against Snowflake.
Only the execution layer changes.

---

## Revised issue scope

### #3 Driver on Fargate (was: Driver on Managed Instances)

**New scope:**
- Replace LMI IaC (capacity_provider.tf, driver.tf) with ECS cluster + task definition
- Strip Lambda runtime loop from entrypoint.sh — restore clean `exec spark-submit`
- ECS task: 4 vCPU / 16 GB, arm64, On-Demand Fargate
- Gateway launches driver task per session via `RunTask`, returns private task IP
- Security group: inbound 15002 from VPC CIDR

**AC:** `RunTask` → wait RUNNING → `spark.sql("select 1")` via `sc://TASK_IP:15002` succeeds.
Record cold start time (task scheduling → gRPC ready).

---

### #4 Multi-node executors (unchanged title, new mechanism)

**New scope:**
- Spark Standalone mode: driver task is also the standalone master (port 7077)
- Executor task definition: `CoarseGrainedExecutorBackend` connecting to driver
- Gateway spawns N executor tasks (Fargate Spot) pointing at driver's private IP
- Security group: executors ↔ driver on ports 7077 + shuffle port range
- Pin ports: `spark.driver.port=7077`, `spark.blockManager.port=7337`

**AC:** 2-stage shuffle query runs across ≥2 executor tasks. Spark UI confirms distribution.

---

### #5 Option C hybrid shuffle (unchanged)

Local ephemeral storage write → async flush to S3 Files mount → recover on executor loss.
EFS/S3 Files mount in task definition via `volumes` + `mountPoints`.

---

### #6 Cold start tier ladder

| Tier | Mechanism | Expected cold start |
|------|-----------|-------------------|
| C (build first) | Fargate On-Demand, no pre-warm | 30-60s |
| B | Fargate with task pre-warming (desired_count ≥ 1) | ~5s (session assignment) |
| A | Dedicated warm task per warehouse | ~0s (always running) |

---

## IaC changes

**Remove:**
- `infra/capacity_provider.tf` — LMI capacity provider
- `infra/driver.tf` — LMI Lambda function

**Add:**
- `infra/ecs.tf` — ECS cluster, task definition (driver + executor), IAM roles
- `infra/security_groups.tf` (or extend existing) — task SG with shuffle ports

**Keep:**
- `infra/ecr.tf` — ECR repo reused
- `infra/vpc.tf` — VPC + subnets unchanged
- `infra/cloudwatch.tf` — log groups, update names
- `infra/vpc_endpoints.tf` — VPCE flag unchanged
- `driver/Dockerfile` — unchanged
- `driver/entrypoint.sh` — simplified (remove Lambda runtime loop)

---

## Driver entrypoint (simplified)

```bash
#!/usr/bin/env bash
set -euo pipefail

export SPARK_LOCAL_IP="0.0.0.0"

exec "${SPARK_HOME}/bin/spark-submit" \
  --class org.apache.spark.sql.connect.service.SparkConnectServer \
  --master "spark://${SPARK_MASTER_HOST:-localhost}:7077" \
  --conf spark.connect.grpc.binding.port=15002 \
  --conf spark.connect.grpc.arrow.maxBatchSize=134217728 \
  --conf spark.driver.host="${SPARK_DRIVER_HOST:-0.0.0.0}" \
  --conf spark.driver.port=7077 \
  --conf spark.blockManager.port=7337 \
  --conf spark.driver.memory="${SPARK_DRIVER_MEMORY:-12g}" \
  --conf spark.ui.enabled=false \
  "${SPARK_HOME}/jars/spark-connect_*.jar"
```

No Lambda runtime API. No hostname hacks. No tee/grep. Just Spark.

---

## GitHub issues to update

- Reopen #3 with new scope (Driver on Fargate)
- Update #4 description (multi-node via Spark Standalone on Fargate)
- #5, #6, #7 unchanged
