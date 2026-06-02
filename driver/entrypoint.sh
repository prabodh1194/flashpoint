#!/usr/bin/env bash
set -euo pipefail

# Resolve our private IP from ECS task metadata.
METADATA_URI="${ECS_CONTAINER_METADATA_URI_V4:-}"
if [ -n "$METADATA_URI" ]; then
  DRIVER_IP=$(curl -s "${METADATA_URI}/task" \
    | jq -r '.Containers[0].Networks[0].IPv4Addresses[0]')
else
  DRIVER_IP="127.0.0.1"
fi

MASTER_URL="spark://${DRIVER_IP}:7077"
echo "Driver IP: ${DRIVER_IP}, master: ${MASTER_URL}"

# Start the Standalone master in the background.
# Executors (separate Fargate tasks) will register with it.
"${SPARK_HOME}/bin/spark-class" org.apache.spark.deploy.master.Master \
  --host "${DRIVER_IP}" \
  --port 7077 \
  --webui-port 8080 &
MASTER_PID=$!

# Wait for master to be ready before submitting.
until curl -sf "http://${DRIVER_IP}:8080/json/" >/dev/null 2>&1; do
  sleep 1
done
echo "Master ready at ${MASTER_URL}"

# Start the Spark Connect server connected to this master.
# spark-submit here acts as the driver application; it registers with
# the master and the master will schedule tasks on registered workers.
exec "${SPARK_HOME}/bin/spark-submit" \
  --class org.apache.spark.sql.connect.service.SparkConnectServer \
  --master "${MASTER_URL}" \
  --conf spark.connect.grpc.binding.port=15002 \
  --conf spark.connect.grpc.arrow.maxBatchSize=134217728 \
  --conf spark.driver.host="${DRIVER_IP}" \
  --conf spark.driver.port=7078 \
  --conf spark.blockManager.port=7337 \
  --conf spark.driver.memory="${SPARK_DRIVER_MEMORY:-4g}" \
  --conf spark.executor.memory="${SPARK_EXECUTOR_MEMORY:-6g}" \
  --conf spark.executor.cores="${SPARK_EXECUTOR_CORES:-2}" \
  --conf spark.dynamicAllocation.enabled=false \
  --conf spark.ui.enabled=true \
  --conf spark.ui.port=4040 \
  "${SPARK_HOME}/jars/spark-connect_*.jar"
