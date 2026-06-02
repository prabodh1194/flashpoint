#!/usr/bin/env bash
set -euo pipefail

: "${SPARK_MASTER_URL:?SPARK_MASTER_URL must be set}"

METADATA_URI="${ECS_CONTAINER_METADATA_URI_V4:-}"
if [ -n "$METADATA_URI" ]; then
  EXECUTOR_IP=$(curl -s "${METADATA_URI}/task" \
    | jq -r '.Containers[0].Networks[0].IPv4Addresses[0]')
else
  EXECUTOR_IP="127.0.0.1"
fi

echo "Starting executor — IP=${EXECUTOR_IP}, master=${SPARK_MASTER_URL}"

exec "${SPARK_HOME}/bin/spark-class" org.apache.spark.deploy.worker.Worker \
  --cores "${SPARK_EXECUTOR_CORES:-2}" \
  --memory "${SPARK_EXECUTOR_MEMORY:-6g}" \
  --host "${EXECUTOR_IP}" \
  "${SPARK_MASTER_URL}"
