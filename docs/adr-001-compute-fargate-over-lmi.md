# ADR-001: ECS Fargate over Lambda Managed Instances for Spark compute

**Status:** Accepted  
**Date:** 2026-06-01  
**Context:** Ember milestone — choosing the compute substrate for Spark driver and executors.

---

## Decision

Use **ECS Fargate** for the Spark Connect driver and executor containers.  
Abandon **Lambda Managed Instances (LMI)** as the compute layer.

---

## Why we tried LMI

Lambda Managed Instances (launched Nov 2025) looked like the perfect primitive:

- EC2-backed containers in your VPC, managed by AWS
- Lambda programming model + event triggers
- Arm64 / Graviton support
- EC2 Reserved Instance pricing (up to 60% discount)
- No cold start on the warm minimum

Initial prototype (Ember #2 / #3) proved the concept: Spark Connect server starts in ~3s on
a real arm64 EC2 instance and the gRPC port binds correctly.

---

## Why LMI doesn't work for Flashpoint

### 1. Persistent server ≠ Lambda invocation model

Spark Connect is a **long-lived gRPC server**. Lambda's execution model assumes
a handler that returns. LMI has no `/init/ready` endpoint — the only way to signal
readiness is `GET /runtime/invocation/next`, which means every execution environment
must run a fake Lambda runtime loop alongside the Spark process forever.

This is a hack. The runtime loop is not the product; Spark Connect is.

### 2. 100 function versions per capacity provider (hard limit, cannot be raised)

Each `publish-version` call burns one slot. For a multi-tenant platform:
- Driver per session = 1 version per session
- Executor pool = additional versions
- Code deploys = more versions

100 slots is exhausted quickly. There is no workaround — the limit is architectural,
not a service quota. ECS tasks have no such limit.

### 3. Scaling reacts to CPU, not to job arrival

LMI scales out when CPU or concurrency saturation is detected on existing instances.
Spark shuffle is **I/O-bound** (waiting on S3 reads/writes) — CPU stays low during
the most critical scaling moments. New executor tasks would not be provisioned when
the job needs them most.

ECS RunTask launches exactly N tasks on demand with no heuristic involved.

### 4. VPC config on the capacity provider is immutable

Subnet IDs and security groups cannot be changed after capacity provider creation.
Any VPC topology change (subnets, AZs, VPCE migration) requires full delete + recreate,
which also requires deleting all attached function versions first.

### 5. No direct port exposure primitive

Clients connect to the driver's gRPC port 15002. With LMI, the instance IP is
not surfaced via any stable API — it requires EC2 describe with a tag filter, and IPs
change on scale events. There is no NLB or Cloud Map integration built in.

ECS has native NLB target group integration and ECS Service Connect for service discovery.

### 6. OpenTofu provider gap

`aws_lambda_capacity_provider` and `aws_lambda_function` (with `capacity_provider_config`)
are not in the AWS provider as of 2026-06. Everything requires `terraform_data` + `local-exec`
CLI workarounds, which means no plan-time validation, no drift detection, and no destroy
orchestration. The entire LMI IaC is held together with shell scripts.

### 7. Container isolation, not Firecracker

Functions on the same capacity provider share EC2 instances at the container level
(not microVM level). In a multi-tenant Flashpoint, this is a security concern. ECS
Fargate uses Firecracker-backed microVM isolation per task — stronger boundary.

---

## Why Fargate

| Requirement | Fargate | LMI |
|-------------|---------|-----|
| Persistent gRPC server | Natural — just a container | Awkward — needs fake runtime loop |
| Dynamic executor launch/terminate | `RunTask` API | Burn a version slot |
| Scale to zero | Yes (service minCount=0) | No (minimum floor always running) |
| Stable endpoint for driver | NLB native integration | Raw IP, changes on restart |
| Service discovery for executors | ECS Service Connect / Cloud Map | DIY |
| Spot for executor cost savings | Fargate Spot (up to 70% cheaper) | No Spot equivalent |
| OpenTofu support | Full provider support | CLI workaround only |
| Spark shuffle networking | awsvpc ENI per task, direct IP-to-IP | Same (VPC) |
| Task isolation | Firecracker microVM per task | Container on shared EC2 |
| Version/slot limit | None | 100 hard cap per capacity provider |

---

## What changes

### Compute layer
- **Remove:** `infra/capacity_provider.tf`, `infra/driver.tf` (LMI resources)
- **Add:** ECS cluster, task definition (driver + executor), Fargate service for driver,
  NLB + target group for gRPC port 15002

### Driver entrypoint
- **Remove:** Lambda runtime API loop (`GET /invocation/next`)
- **Restore:** Clean `exec spark-submit` — no wrapper needed

### Executor launch
- **Pattern:** Gateway calls `ecs:RunTask` per job with N replicas; terminates tasks
  on job completion. No persistent executor service needed.

### Networking
- awsvpc mode: each task gets its own ENI + private IP
- Security group on tasks: allow inbound 15002 (gRPC) + shuffle port range from driver SG
- NLB for driver: stable DNS endpoint for Spark Connect clients
- ECS Service Connect or Cloud Map for executor discovery by driver

### Cost model shift
- Fargate On-Demand: ~$0.04048/vCPU-hour + ~$0.004445/GB-hour (arm64 Graviton)
- Fargate Spot: up to 70% cheaper — use for executor tasks (interruptible mid-job with
  Option C shuffle recovery from S3 Files)
- Fargate Savings Plans: up to 50% discount on On-Demand for driver (always-on)

---

## What stays the same

- ECR repo (`flashpoint-dev-driver`) — image reused as-is
- VPC, subnets, security groups — same topology
- `driver/Dockerfile` — no changes needed
- `driver/entrypoint.sh` — simplified (remove Lambda runtime loop)
- CloudWatch log group — same
- S3 Files for shuffle (Ember #5) — unaffected

---

## Ember milestone replan

| Issue | Previous plan | New plan |
|-------|--------------|----------|
| #3 Driver on Managed Instances | ~~LMI capacity provider~~ | Fargate service + NLB (reopen) |
| #4 Multi-node executors | ~~LMI executor functions~~ | `RunTask` API, Fargate Spot |
| #5 Option C shuffle | S3 Files — unchanged | S3 Files — unchanged |

Issue #3 will be re-scoped to "Driver on Fargate" and reopened.
