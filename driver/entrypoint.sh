#!/usr/bin/env bash
set -euo pipefail

SPARK_ROLE="${SPARK_ROLE:-driver}"

METADATA_URI="${ECS_CONTAINER_METADATA_URI_V4:-}"
if [ -n "$METADATA_URI" ]; then
  IP=$(curl -s "${METADATA_URI}/task" \
    | jq -r '.Containers[0].Networks[0].IPv4Addresses[0]')
else
  IP="127.0.0.1"
fi

if [ "$SPARK_ROLE" = "executor" ]; then
  echo "Starting executor — IP=${IP}, master=${SPARK_MASTER_URL}"

  exec "${SPARK_HOME}/bin/spark-class" org.apache.spark.deploy.worker.Worker \
    --cores "${SPARK_EXECUTOR_CORES:-2}" \
    --memory "${SPARK_EXECUTOR_MEMORY:-6g}" \
    --host "${IP}" \
    "${SPARK_MASTER_URL:?SPARK_MASTER_URL required for executor}"
fi

# --- Driver path ---

MASTER_URL="spark://${IP}:7077"
echo "Driver IP: ${IP}, master: ${MASTER_URL}"

"${SPARK_HOME}/bin/spark-class" org.apache.spark.deploy.master.Master \
  --host "${IP}" \
  --port 7077 \
  --webui-port 8080 &
MASTER_PID=$!

until curl -sf "http://${IP}:8080/json/" >/dev/null 2>&1; do
  sleep 1
done
echo "Master ready at ${MASTER_URL}"

exec "${SPARK_HOME}/bin/spark-submit" \
  --class org.apache.spark.sql.connect.service.SparkConnectServer \
  --master "${MASTER_URL}" \
  --conf spark.connect.grpc.binding.port=15002 \
  --conf spark.connect.grpc.arrow.maxBatchSize=134217728 \
  --conf spark.driver.host="${IP}" \
  --conf spark.driver.port=7078 \
  --conf spark.blockManager.port=7337 \
  --conf spark.driver.memory="${SPARK_DRIVER_MEMORY:-4g}" \
  --conf spark.executor.memory="${SPARK_EXECUTOR_MEMORY:-6g}" \
  --conf spark.executor.cores="${SPARK_EXECUTOR_CORES:-2}" \
  --conf spark.dynamicAllocation.enabled=false \
  --conf spark.ui.enabled=true \
  --conf spark.ui.port=4040 \
  "${SPARK_HOME}/jars/spark-connect_*.jar"
