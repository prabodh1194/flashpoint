#!/bin/bash
set -euo pipefail

# Full Flashpoint teardown — stops Fargate tasks, destroys the stack, and
# verifies nothing Flashpoint remains (zero AWS spend afterwards).
#
# Usage:  scripts/teardown.sh [tfvars-file]   (default: dev.tfvars)

cd "$(dirname "$0")/../infra"

TFVARS="${1:-dev.tfvars}"
export AWS_PROFILE="${AWS_PROFILE:-personal-aws-iam}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

echo "== 1/3 stopping Fargate tasks (active tasks block cluster deletion)"
CLUSTER=$(aws ecs list-clusters --query 'clusterArns[?contains(@, `flashpoint`) != `false`] | [0]' --output text 2>/dev/null || true)
if [ -n "$CLUSTER" ] && [ "$CLUSTER" != "None" ]; then
  TASKS=$(aws ecs list-tasks --cluster "$CLUSTER" --query 'taskArns' --output text 2>/dev/null || true)
  if [ -n "$TASKS" ]; then
    for t in $TASKS; do
      aws ecs stop-task --cluster "$CLUSTER" --task "$t" >/dev/null
    done
    echo "   stopped: $TASKS"
  fi
fi

echo "== 2/3 tofu destroy"
tofu destroy -var-file="$TFVARS" -auto-approve -no-color

echo "== 3/3 verifying nothing remains"
FAIL=0
check() {
  local label="$1" result="$2"
  if [ -z "$result" ] || [ "$result" = "None" ]; then
    echo "   PASS  $label"
  else
    echo "   FAIL  $label: $result"
    FAIL=1
  fi
}

check "EC2 instances" \
  "$(aws ec2 describe-instances --query 'Reservations[].Instances[?State.Name!=`terminated`].InstanceId' --output text 2>/dev/null || true)"
check "EBS volumes" \
  "$(aws ec2 describe-volumes --query 'Volumes[].VolumeId' --output text 2>/dev/null || true)"
check "flashpoint ECS clusters" \
  "$(aws ecs list-clusters --query 'clusterArns[?contains(@, `flashpoint`)] | [0]' --output text 2>/dev/null || true)"
check "flashpoint DynamoDB tables" \
  "$(aws dynamodb list-tables --query 'TableNames[?starts_with(@, `flashpoint`)] | [0]' --output text 2>/dev/null || true)"
check "flashpoint S3 buckets" \
  "$(aws s3api list-buckets --query 'Buckets[?starts_with(Name, `flashpoint`)].Name | [0]' --output text 2>/dev/null || true)"
check "flashpoint ECR repos" \
  "$(aws ecr describe-repositories --query 'repositories[?starts_with(repositoryName, `flashpoint`)].repositoryName | [0]' --output text 2>/dev/null || true)"

if [ "$FAIL" = "1" ]; then
  echo "   teardown incomplete — investigate the FAIL lines above"
  exit 1
fi
echo "   Flashpoint is fully torn down — no recurring Flashpoint costs."
