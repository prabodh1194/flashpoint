# Infra

OpenTofu stack for everything AWS. Provider profile `personal-aws`, region `us-east-1`,
prefix `flashpoint-dev` (`locals.tf`).

## Files

| File | Resources |
|---|---|
| `vpc.tf` | VPC, public subnets (private only when `enable_vpc_endpoints = true`) |
| `vpc_endpoints.tf` | S3 gateway + ECR/CWL interface endpoints (production mode) |
| `ecs.tf` | cluster, FARGATE + FARGATE_SPOT capacity providers, Spark task SG, IAM, driver + executor task definitions |
| `ecr.tf` | driver image repo + keep-last-5 lifecycle |
| `gateway.tf` | gateway EC2 (`t4g.small`) + IAM: ECS, DynamoDB, S3, pricing, Cost Explorer, tagging |
| `gateway-init.sh` | EC2 user-data template: installs uv, clones `gateway_branch`, writes env, systemd unit |
| `dynamodb.tf` | `warehouses` (hash `name`), `meters` (`pk`/`sk`), `queries` (`qid` + TTL) |
| `s3.tf` | query-results bucket, 7-day expiry |
| `cloudwatch.tf` | driver + executor log groups, 1-day retention |
| `outputs.tf` | endpoint, ECR URL, task-def and subnet IDs |

## Rules

- Driver runs on-demand FARGATE, 4 vCPU / 16 GB. Executors run FARGATE_SPOT, 2 vCPU / 8 GB
  each. Both ARM64. `ecs_tasks.launch_driver_with_executors` assumes this.
- The driver/executor image tag in `ecs.tf` is hardcoded (`<repo-url>:<tag>`). After pushing
  a new driver image, update both task definitions; `tofu apply` does not pull `latest`.
- `dev.tfvars` is gitignored and sets `gateway_branch`. Dev keeps
  `enable_vpc_endpoints = false` for zero idle cost; production flips it true.
- `gateway-init.sh` clones from GitHub at boot — the branch must exist on origin.
- Teardown: `scripts/teardown.sh` stops tasks, destroys the stack, and verifies zero
  remaining Flashpoint resources.

## Commands

    tofu init
    tofu plan  -var-file=dev.tfvars
    tofu apply -var-file=dev.tfvars
