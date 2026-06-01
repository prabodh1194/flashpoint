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

### #24 EC2 gateway skeleton (NEW — Ember)

Minimal always-on EC2 control plane that launches Fargate tasks and returns their IPs.
Truly minimal: single process, in-memory session→IP map, no persistence. Just enough to
drive #3/#4 end-to-end. Full hardening (DynamoDB, HA, reconnect, reaping) → Kindle #8/#10.

**Scope:**
- t4g.small (arm64) always-on
- `RunTask(driver)`, `RunTask(executor×N)`, `describe-tasks` to resolve private IPs
- In-memory session→task-IP map
- Basic driver-task health check

**AC:** one API call launches a driver task and returns `sc://TASK_IP:15002`; a client query
succeeds through it.

Depends on #3. Blocks #4.

---

### #4 Multi-node executors (new mechanism)

**New scope:**
- Spark Standalone mode: driver task is also the standalone master (port 7077)
- Executor task definition: `CoarseGrainedExecutorBackend` connecting to driver
- Gateway (#24) spawns N executor tasks (Fargate Spot) pointing at driver's private IP
- Security group: executors ↔ driver on ports 7077 + shuffle port range
- Pin ports: `spark.driver.port=7077`, `spark.blockManager.port=7337`

**AC:** 2-stage shuffle query runs across ≥2 executor tasks. Spark UI confirms distribution.

---

### #5 Option C hybrid shuffle (unchanged)

Local ephemeral storage write → async flush to S3 Files mount → recover on executor loss.
EFS/S3 Files mount in task definition via `volumes` + `mountPoints`.

---

### #6 Cold start tier ladder

Fast-start is still core — only the Lambda mechanism (SnapStart) is dropped, replaced by
Fargate-native techniques. Keep the concept, drop the Lambda primitive.

| Tier | Mechanism | Expected cold start |
|------|-----------|-------------------|
| C (build first) | Fargate On-Demand, no pre-warm | 30-60s |
| B | SOCI (lazy image pull) + AppCDS (JVM class warmup) + small pre-warmed pool | ~5s assignment |
| A | Dedicated always-warm task per warehouse | ~0s |

SOCI attacks the image-pull phase (20s→~2s for our 613 MB image); AppCDS attacks the
JVM-boot phase. These are the Fargate analogs to what SnapStart did on Lambda.

---

## IaC changes

**Tear down (live in tofu state — must `tofu destroy -target` or remove from config):**
- `terraform_data.capacity_provider` — LMI capacity provider (CLI-managed)
- `terraform_data.driver_function` — LMI Lambda function (CLI-managed)
- `aws_iam_role.capacity_provider_operator` + `..._ec2` attachment — operator role
- `aws_iam_role.capacity_provider` + `..._basic` attachment — replaced by ECS task/exec roles
- delete files: `infra/capacity_provider.tf`, `infra/driver.tf`

**Add:**
- `infra/ecs.tf` — ECS cluster, driver + executor task definitions
- `infra/iam.tf` — ECS execution role + Spark task role
- `infra/gateway.tf` — EC2 gateway instance + its IAM (RunTask/describe-tasks perms)
- extend SG (rename `aws_security_group.capacity_provider` → `..._task`): inbound 15002,
  7077, 7337 from VPC CIDR

**Keep as-is:**
- `infra/ecr.tf` — ECR repo reused (image unchanged)
- `infra/vpc.tf` — VPC + public subnets + IGW + route tables
- `infra/cloudwatch.tf` — log group (rename to /flashpoint/driver)
- `infra/vpc_endpoints.tf` — `enable_vpc_endpoints` flag unchanged
- `driver/Dockerfile` — unchanged
- `driver/entrypoint.sh` — simplified (remove Lambda runtime loop + all the hacks)

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
