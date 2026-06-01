# AWS ECS Fargate — Technical Deep Dive for Flashpoint

> Status: working notes, not committed. Last updated: 2026-06-01.
> Sources: AWS docs, Kimi research, ADR-001.

---

## Why Fargate for Spark Connect

Spark Connect is a **persistent gRPC server** that holds a SparkSession in memory.
It requires:
- Long-lived HTTP/2 connections (hours per interactive session)
- Stable private IP for executor-to-driver communication
- No invocation timeout
- Direct port exposure to VPC clients

None of these are natural fits for Lambda. Fargate is the correct substrate.

---

## ECS Fundamentals

```
ECS Cluster          → logical grouping of compute capacity
  └── Service        → maintains N running tasks, handles restarts, integrates with NLB
        └── Task     → one running instance of a task definition (your containers)
              └── Container → the actual Docker container
```

**Task vs Service:**
- **Service** — for long-lived servers (Spark Connect driver). ECS maintains desired count,
  replaces failed tasks, registers/deregisters with NLB target group.
- **RunTask** — for ephemeral jobs (Spark executors). Launch N tasks, they run and exit.
  No service overhead. Pay only for task runtime.

**Fargate launch type:** AWS manages the underlying EC2 fleet. You specify vCPU + memory;
AWS picks the instance. No fleet to manage.

**Network mode:** `awsvpc` — each task gets its own ENI + private IP. Required for Fargate.

---

## Networking for Persistent gRPC

### NLB vs ALB

For Spark Connect port 15002:

| | NLB (TCP) | ALB (HTTP/2) |
|--|-----------|--------------|
| Long-lived connections | ✅ No timeout | ⚠️ Idle timeout max 4000s |
| gRPC | ✅ Passthrough | ✅ Native but needs TLS |
| Complexity | Low | Medium |
| Health check | TCP | gRPC health proto |

**Use NLB.** Spark clients hold connections for hours during interactive sessions.
ALB's idle connection timeout will kill them.

### Session affinity (sticky sessions)

Each Spark Connect server holds **one SparkSession** — the session is stateful.
NLB does NOT do sticky sessions natively for TCP. Options:
1. **Client-side routing** — gateway assigns client to a specific task IP; client always
   connects to that IP directly (bypasses NLB after initial assignment).
2. **One driver per session** — each session gets its own Fargate task. Gateway manages
   the mapping. Cleanest for Flashpoint (matches Snowflake warehouse-per-session model).

**Flashpoint choice: one driver task per warehouse session.** Gateway launches a driver task
on session start, returns the task's private IP to the client, client connects directly.
NLB is optional at that point (or used as the management plane endpoint only).

### Task discovery

Each Fargate task in `awsvpc` mode has a private IP in your subnet. To find it:
```bash
aws ecs describe-tasks --cluster flashpoint --tasks TASK_ARN \
  --query 'tasks[0].attachments[0].details[?name==`privateIPv4Address`].value'
```

Or use **AWS Cloud Map** — ECS Service Connect registers tasks automatically with
a DNS name. But for per-session tasks (RunTask, not Service), register manually:
```bash
aws servicediscovery register-instance ...
```

---

## Task Definition for Spark Connect Driver

```hcl
resource "aws_ecs_task_definition" "driver" {
  family                   = "flashpoint-driver"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "4096"   # 4 vCPU
  memory                   = "16384"  # 16 GB
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.spark_task.arn

  container_definitions = jsonencode([{
    name      = "spark-connect"
    image     = "${aws_ecr_repository.driver.repository_url}:latest"
    essential = true

    portMappings = [
      { containerPort = 15002, protocol = "tcp" },  # Spark Connect gRPC
      { containerPort = 4040,  protocol = "tcp" }   # Spark UI (optional)
    ]

    environment = [
      { name = "SPARK_LOCAL_IP",       value = "0.0.0.0" },
      { name = "SPARK_DRIVER_MEMORY",  value = "12g" }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = "/flashpoint/driver"
        awslogs-region        = "us-east-1"
        awslogs-stream-prefix = "ecs"
      }
    }

    # No healthCheck needed for RunTask pattern — gateway polls task status
  }])
}
```

**Key difference from LMI:** No runtime API loop. Entrypoint is just `exec spark-submit`.
Clean, no hacks.

---

## Driver Launch Pattern (per session)

```bash
# Gateway launches a driver task per warehouse session
TASK=$(aws ecs run-task \
  --cluster flashpoint \
  --task-definition flashpoint-driver \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={
    subnets=[subnet-xxx],
    securityGroups=[sg-xxx],
    assignPublicIp=DISABLED
  }" \
  --query 'tasks[0].taskArn' --output text)

# Wait for RUNNING state (~30-60s cold start on Fargate)
aws ecs wait tasks-running --cluster flashpoint --tasks $TASK

# Get private IP
DRIVER_IP=$(aws ecs describe-tasks --cluster flashpoint --tasks $TASK \
  --query 'tasks[0].attachments[0].details[?name==`privateIPv4Address`].value' \
  --output text)

# Return sc://DRIVER_IP:15002 to client
```

---

## Executor Fleet Pattern (per job)

Spark executors are launched by the Spark driver automatically when using
`local[*]` — but that's single-node (all in the driver task).

For **multi-node Spark**, the driver needs to reach executor JVMs over the network.
Two approaches:

### Option A: Spark Standalone mode
- Run a standalone Spark master + workers
- Workers are Fargate tasks registered with the master
- Driver submits to `spark://master:7077`
- Workers handle task execution, report back to driver

### Option B: Spark on YARN / Kubernetes
- Kubernetes on EKS is the standard for Spark multi-node
- Fargate on EKS is possible but adds complexity

### Option C (Flashpoint approach): Spark Standalone on Fargate
1. Driver task starts in `local[*]` mode initially
2. Gateway's `RunTask` call spawns N executor tasks pointing at driver's IP
3. Executor tasks run `spark-class org.apache.spark.executor.CoarseGrainedExecutorBackend`
4. Executors register with driver via `spark://DRIVER_IP:7077`

This is the cleanest Fargate-native approach without Kubernetes overhead.

---

## Fargate Spot for Executors

Fargate Spot: up to **70% cheaper** than On-Demand. AWS can interrupt with 2-minute warning.

**Safe for Spark executors** because:
- Spark's DAG scheduler retries failed tasks on other executors
- With Option C hybrid shuffle (Ember #5), shuffle data on S3 Files survives executor loss
- SIGTERM → 2-minute window → executor can flush in-flight shuffle to S3

**Not safe for the driver** — session loss if interrupted. Driver = On-Demand.

```hcl
resource "aws_ecs_task_definition" "executor" {
  # ... same as driver but different cpu/memory
}

# In RunTask call for executors:
capacity_provider_strategy {
  capacity_provider = "FARGATE_SPOT"
  weight            = 100
}
```

---

## Scaling

### Driver pool (Service-based)
For a shared pool of warm drivers:
```hcl
resource "aws_ecs_service" "driver_pool" {
  cluster         = aws_ecs_cluster.flashpoint.id
  task_definition = aws_ecs_task_definition.driver.arn
  desired_count   = 3  # warm minimum

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }

  # No NLB needed for per-session direct-IP model
}
```

Scale with Application Auto Scaling on custom metric (ActiveSessions):
```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --resource-id service/flashpoint/driver-pool \
  --scalable-dimension ecs:service:DesiredCount \
  --min-capacity 1 \
  --max-capacity 50
```

### Scale to zero
Set `desired_count = 0` on the service → all tasks stop → $0 compute.
Cold start on next request: ~30-60s for Fargate (image pull + JVM init).

---

## Cold Start

| Phase | Time |
|-------|------|
| Fargate task scheduling | 5-15s |
| Container pull from ECR (same-region, cached) | 5-20s |
| JVM startup + Spark init | 10-15s |
| **Total (warm image cache)** | **20-50s** |
| **Total (cold image cache)** | **30-90s** |

Our 613 MB image: ECR in same region, layers cached after first pull per node → ~20-30s total.

**Tier C baseline** from the plan (~10-15s) isn't achievable on Fargate — realistic is 30-60s.
Tier A (warm, zero cold start) = keep tasks running at desired_count ≥ 1.

---

## Storage

- **Ephemeral storage**: 20 GB default, up to 200 GB per task (`ephemeral_storage.size_in_gib`).
  Lost when task stops — use for local shuffle temp files.
- **EFS mounts**: Fargate tasks can mount EFS (and by extension S3 Files, which is NFS over S3).
  Mount in task definition via `volumes` + `mountPoints`.
- **S3 Files for shuffle** (Ember #5): mount via EFS access point in task definition;
  shuffle plugin writes locally, async flushes to S3 Files mount.

---

## IAM

Two roles needed:

**Execution role** (ECS agent, not your code):
- `ecr:GetAuthorizationToken`, `ecr:BatchGetImage` — pull from ECR
- `logs:CreateLogStream`, `logs:PutLogEvents` — CloudWatch Logs
- Managed policy: `AmazonECSTaskExecutionRolePolicy`

**Task role** (your code's permissions):
- `s3:GetObject`, `s3:PutObject` — S3 shuffle + data lake
- `glue:GetTable`, `glue:GetDatabase` — Glue catalog (Forge)
- `cloudwatch:PutMetricData` — metering (Kindle)

---

## OpenTofu Resources Needed

```
aws_ecs_cluster
aws_ecs_task_definition        (driver + executor separate)
aws_ecs_service                (driver pool — optional, for warm minimum)
aws_iam_role                   (execution role + task role)
aws_iam_role_policy_attachment (attach managed policies)
aws_cloudwatch_log_group       (driver + executor log groups)
aws_security_group             (task SG: inbound 15002 + shuffle ports)
```

NLB only needed if using a shared driver pool with client-side routing.
For per-session RunTask pattern, no NLB needed.

---

## Key Gotchas

1. **Driver is stateful** — SparkSession lives in the task. Task death = session loss.
   Gateway must track task ARN → session mapping and detect task failure.

2. **awsvpc = 1 ENI per task** — each task consumes one ENI slot. Account default:
   ~5 ENIs per subnet per AZ. Request limit increase before scaling beyond ~50 tasks.
   Use larger subnets (/20 or /18) to avoid ENI exhaustion.

3. **No Fargate GPU** — same as LMI. GPU workloads need ECS on EC2.

4. **Fargate Spot 2-minute warning** — executors must flush shuffle data within this window.
   Option C hybrid shuffle (S3 Files) makes this safe.

5. **Same-region ECR** — always use ECR in the same region as ECS cluster. Cross-region
   pulls add latency and cost.

6. **Container Insights** — enable on cluster for Fargate-level CPU/memory metrics.
   Not enabled by default.

7. **Spark executor discovery** — executors need to reach driver on shuffle port (random
   high port range by default). Pin with `spark.driver.port` and `spark.blockManager.port`
   and open those in the security group.

---

## Flashpoint Architecture (Ember → Kindle)

```
Client (pyspark-connect, worksheet)
  │ gRPC sc://IP:15002
  ▼
Gateway (Kindle #8) ─── RunTask(driver) ──▶ ECS Task: Spark Connect Driver
  │                      returns task IP       │ local[*] or standalone master
  │                                            │ port 15002 (gRPC)
  │                                            │ port 7077 (Spark master)
  │                                            ▼
  └─── RunTask(executor×N) ──▶ ECS Tasks: Spark Executors (Spot)
                                    register with driver:7077
                                    shuffle → S3 Files (Ember #5)
```

---

## Cost Estimate (us-east-1, arm64 Graviton)

| Resource | Spec | On-Demand/hr | Spot/hr |
|----------|------|-------------|---------|
| Driver task | 4 vCPU, 16 GB | ~$0.22 | N/A (On-Demand) |
| Executor task | 2 vCPU, 8 GB | ~$0.11 | ~$0.033 |
| NLB (if used) | — | ~$0.008/hr + LCU | — |

3 warm drivers 24/7: ~$475/month. Scale to zero outside business hours: ~$140/month.
Executor cost: pay-per-job-duration (seconds billing).
