#!/usr/bin/env bash
set -euo pipefail

# Resolve our private IP from the ECS task metadata endpoint.
# Executors need a routable address to register with the master.
METADATA_URI="${ECS_CONTAINER_METADATA_URI_V4:-}"
if [ -n "$METADATA_URI" ]; then
  DRIVER_IP=$(curl -s "${METADATA_URI}/task" | python3 -c \
    "import sys, json; nets=json.load(sys.stdin)['Containers'][0]['Networks']; print(nets[0]['IPv4Addresses'][0])")
else
  # Fallback for local runs
  DRIVER_IP="127.0.0.1"
fi

SPARK_MASTER_URL="spark://${DRIVER_IP}:7077"
echo "Starting Spark Connect — driver IP=${DRIVER_IP}, master=${SPARK_MASTER_URL}"

exec "${SPARK_HOME}/bin/spark-submit" \
  --class org.apache.spark.sql.connect.service.SparkConnectServer \
  --master "${SPARK_MASTER_URL}" \
  --conf spark.connect.grpc.binding.port=15002 \
  --conf spark.connect.grpc.arrow.maxBatchSize=134217728 \
  --conf spark.driver.host="${DRIVER_IP}" \
  --conf spark.driver.port=7078 \
  --conf spark.blockManager.port=7337 \
  --conf spark.driver.memory="${SPARK_DRIVER_MEMORY:-4g}" \
  --conf spark.executor.memory="${SPARK_EXECUTOR_MEMORY:-6g}" \
  --conf spark.executor.cores="${SPARK_EXECUTOR_CORES:-2}" \
  --conf spark.ui.enabled=false \
  --conf spark.master.rest.enabled=true \
  "${SPARK_HOME}/jars/spark-connect_*.jar"
