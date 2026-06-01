# AWS Lambda Managed Instances — Technical Deep Dive

> Status: working notes, not committed. Last updated: 2026-06-01.
> Sources: AWS docs (API 2025-11-30), Kimi research, hands-on Ember #2/#3.

---

## What It Is

Lambda Managed Instances (LMI) runs Lambda functions on **EC2 Nitro instances in your own VPC**,
not on shared Lambda fleets. AWS manages provisioning, patching, and rotation. You pay EC2
On-Demand + 15% management fee, but gain EC2 hardware selection, multi-concurrency per execution
environment, and EC2 commitment discounts (RIs, Savings Plans).

**Core trade-off:** predictable steady-state throughput at EC2 cost vs bursty elasticity at
per-invocation Lambda cost. Break-even ≈ 2.5M requests/month.

---

## Three-Layer Architecture

```
Capacity Provider     → defines VPC, instance types, scaling policy (your full control)
  └── Managed Instances  → EC2 launched in your VPC (AWS manages, 14-day rotation, no SSH)
        └── Execution Environments → containers running your function code
```

**Container isolation, NOT Firecracker microVMs.** Functions on the same capacity provider share
EC2 instances. Compromised function can affect others → separate prod/dev/tenant into distinct
capacity providers.

---

## Capacity Provider

### Create (CLI)
```bash
aws lambda create-capacity-provider \
  --capacity-provider-name my-cp \
  --vpc-config SubnetIds=[...],SecurityGroupIds=[...] \
  --permissions-config CapacityProviderOperatorRoleArn=arn:aws:iam::ACCT:role/operator \
  --instance-requirements Architectures=[arm64] \
  --capacity-provider-scaling-config ScalingMode=Auto,MaxVCpuCount=400
```

### Immutable fields (set once, never change)
- `VpcConfig` (SubnetIds, SecurityGroupIds)
- `PermissionsConfig` (operator role ARN)
- `InstanceRequirements` (architecture, allowed/excluded types)
- `KmsKeyArn`

### Updatable fields
- `CapacityProviderScalingConfig` only (scaling mode, max vCPU, target CPU)

### IAM — Operator Role
- Attach managed policy: `AWSLambdaManagedEC2ResourceOperator`
- Trust principal: `scaler.lambda.amazonaws.com`
- Separate from the Lambda execution role

### Limits
| Limit | Value |
|-------|-------|
| Capacity providers per account/region | 1,000 |
| **Function versions per capacity provider** | **100 (hard, cannot be raised)** |
| Write API rate | 1 req/s (Create/Update/Delete) |

### States
`Pending` → `Active` → `Deleting` (or `Failed`)

Delete: must remove all attached function versions first; EC2 decommissioning takes minutes.

---

## Function Creation

```bash
aws lambda create-function \
  --function-name my-fn \
  --package-type Image \
  --code ImageUri=ACCOUNT.dkr.ecr.REGION.amazonaws.com/repo:tag \
  --role arn:aws:iam::ACCT:role/execution-role \
  --architectures arm64 \
  --memory-size 4096 \
  --timeout 900 \
  --capacity-provider-config 'LambdaManagedInstancesCapacityProviderConfig={
      CapacityProviderArn=arn:aws:lambda:REGION:ACCT:capacity-provider:my-cp,
      PerExecutionEnvironmentMaxConcurrency=8,
      ExecutionEnvironmentMemoryGiBPerVCpu=4
    }'
```

### Key rules
- `CapacityProviderConfig` is set **at CreateFunction only** — immutable post-creation.
- **Published versions required.** `$LATEST` never activates on LMI. Always `publish-version`.
- Memory: **2 GB – 32 GB** (requires `hashicorp/aws ≥ 6.29.0` for >10 GB in Terraform/OpenTofu).
- No VPC config on the function — networking is inherited from the capacity provider.

### `PerExecutionEnvironmentMaxConcurrency`
Max concurrent invocations per execution environment. Defaults: Java=32/vCPU, Node=64/vCPU.
Max 64 per vCPU.

### `ExecutionEnvironmentMemoryGiBPerVCpu`
| Ratio | Use case |
|-------|----------|
| 2:1 | Compute-heavy (batch, data crunching) |
| 4:1 | Balanced (API handlers) |
| 8:1 | Memory-heavy (large datasets, ML models) |

### Function States
- `Pending` — provisioning
- `Active` — ready
- `ActiveNonInvocable` — exists but cannot receive invocations (CP issue, min=0)
- `Failed` — init timeout or error
- `Deactivated` / `Deactivating` — min=max=0 set

---

## Scaling

- **Scaling signal: CPU utilization + concurrency saturation** — NOT traffic volume.
- I/O-bound workloads (Spark shuffle waiting on S3) won't trigger scale-out. Monitor
  `ExecutionEnvironmentConcurrency` not CPU if your workload is I/O-bound.
- Traffic spikes >2× within 5 minutes → 429 throttles while new instances spin up.
- Default minimum: **3 execution environments** (one per AZ for HA).
- Scale-to-zero: NOT supported. Min floor keeps instances running 24/7.
- To stop billing: `PutFunctionScalingConfig` with `MinExecutionEnvironments=0,
  MaxExecutionEnvironments=0` → state becomes `Deactivated`.

### Scaling controls
```bash
aws lambda put-function-scaling-config \
  --function-name my-fn:PUBLISHED \
  --scaling-config MinExecutionEnvironments=3,MaxExecutionEnvironments=50
```

Use EventBridge Scheduler targeting `PutFunctionScalingConfig` for scheduled scale-up/down
(cost saving outside business hours).

---

## Runtime API

`AWS_LAMBDA_RUNTIME_API=127.0.0.1:9001`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/2018-06-01/runtime/invocation/next` | GET | Pull next invocation; **doubles as init-complete signal** |
| `/2018-06-01/runtime/invocation/{id}/response` | POST | Send success response |
| `/2018-06-01/runtime/invocation/{id}/error` | POST | Report invocation error |
| `/2018-06-01/runtime/init/error` | POST | Report init failure before any invocation |

**There is NO `/init/ready` endpoint.** It returns 404. The init phase is considered complete
when the first worker calls `GET /invocation/next`.

Multiple workers can call `/next` concurrently up to `AWS_LAMBDA_MAX_CONCURRENCY`.

---

## Container Environment

- Runs as `sbx_user1051` (not root).
- `/etc/hosts` is read-only at runtime — cannot write hostname entries.
- Hostname is a UUID string with no DNS resolution.
- `/tmp` is writable, shared across concurrent invocations — use unique filenames or file locks.
- `AWS_*` credential env vars are injected — unset them before spark-submit to prevent
  `SparkHadoopUtil.appendS3CredentialsFromEnvironment` UUID hostname crash.

### Working entrypoint pattern (Flashpoint Ember #3)
```bash
#!/usr/bin/env bash
set -euo pipefail

# Unset AWS creds so SparkHadoopUtil skips getLocalHost() call
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN
export SPARK_LOCAL_IP=127.0.0.1
export SPARK_LOCAL_HOSTNAME=localhost

SPARK_LOG=/tmp/spark-connect.log

# stdbuf -oL: force line-buffered output so tee flushes each line immediately
stdbuf -oL spark-submit ... 2>&1 | tee "${SPARK_LOG}" &
SPARK_PID=$!

if [[ -n "${AWS_LAMBDA_RUNTIME_API:-}" ]]; then
  until grep -q "Spark Connect server started at" "${SPARK_LOG}" 2>/dev/null; do
    sleep 1
  done
  RUNTIME="http://${AWS_LAMBDA_RUNTIME_API}/2018-06-01/runtime"
  while kill -0 $SPARK_PID 2>/dev/null; do
    RESP=$(curl -sf "${RUNTIME}/invocation/next" 2>/dev/null || true)
    REQ_ID=$(echo "${RESP}" | grep -o '"awsRequestId":"[^"]*"' | cut -d'"' -f4 || true)
    [[ -n "${REQ_ID}" ]] && curl -sf -X POST \
      "${RUNTIME}/invocation/${REQ_ID}/response" -d '{"statusCode":200}' >/dev/null 2>&1 || true
  done
fi

wait $SPARK_PID
```

---

## Networking

- **VPC is mandatory.** Without outbound connectivity (NAT or VPC endpoints), functions execute
  but **logs and traces are silently lost**.
- Capacity provider owns VPC config; function inherits it.
- **Public subnet + public IP**: works for dev. Outbound to ECR, CloudWatch, S3 via internet.
- **Private subnet + NAT gateway**: standard. Moderate cost (~$32/month per NAT).
- **Private subnet + VPC endpoints**: production. ECR DKR/API + S3 (free Gateway) + CloudWatch
  Logs. ~$7.20/month per interface endpoint per AZ.

### Finding managed instances
Instances are visible in EC2 console with tag `aws_ec2_managed-launch:lambda-managed-instances`.
Not returned by default `describe-instances` — filter by that tag.

### Port exposure
Raw VPC networking. Other VPC resources connect to instance private IP + port directly.
Security groups on the capacity provider control inbound. Use NLB or AWS Cloud Map for stable
addressing (instance IPs change on scale events).

---

## Cost Model

| Component | Standard Lambda | LMI |
|-----------|----------------|-----|
| Requests | $0.20/million | $0.20/million |
| Compute | Per GB-second | None |
| Infrastructure | None | EC2 On-Demand + 15% mgmt fee |

**EC2 commitment discounts apply:**
| Commitment | Standard Lambda | LMI |
|------------|----------------|-----|
| None | 0% | 0% |
| 1-yr Compute SP | 17% | 36% |
| 3-yr Compute SP | 17% | 56% |
| 1-yr EC2 RI | N/A | 40% |
| 3-yr EC2 RI | N/A | **60%** |

Break-even vs standard Lambda: ~2.5M requests/month. Above that, LMI grows cheaper fast.

---

## Limits

| Limit | Value |
|-------|-------|
| Memory | 2 GB – 32 GB |
| Max timeout | 15 min (900s) |
| Function versions per CP | **100 (hard)** |
| Capacity providers/account | 1,000 |
| Supported runtimes | Python 3.13+, Node 22+, Java 21+, .NET 8+, Rust |
| GPU instances | NOT supported |

---

## Flashpoint Design Implications

### 100-version limit
Do NOT create a new Lambda version per executor per Spark job — you'll burn through 100 fast.
Instead: fixed executor function invoked with per-job config in the payload.

### Separate capacity providers
- Driver CP: driver function only
- Executor pool CP: all executor functions
- Future: per-tenant CPs for isolation

### Scaling for Spark
Spark executors are CPU-bound during computation → CPU-based scaling will trigger correctly.
During shuffle (I/O-bound) → won't scale. Size executor pool to peak job parallelism at creation,
not dynamically.

### IaC
- Upgrade `hashicorp/aws` to `~> 6.29` (current: `~> 5.0`) for full LMI support.
- Flip `enable_vpc_endpoints = true` for any environment where logs must not be lost.

### CloudFormation resource type
`AWS::Lambda::CapacityProvider` — available in CloudFormation/CDK if using those tools.
OpenTofu `aws_lambda_capacity_provider` resource not yet in provider as of 2026-06.
Use `terraform_data` + `local-exec` AWS CLI workaround (see `infra/capacity_provider.tf`).
