#!/usr/bin/env bash
set -euo pipefail

# Lambda container hostnames are UUID strings with no DNS entry.
# Unsetting AWS credential vars makes SparkHadoopUtil skip the hostname lookup.
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN
export SPARK_LOCAL_IP=127.0.0.1
export SPARK_LOCAL_HOSTNAME=localhost

SPARK_LOG=/tmp/spark-connect.log

# stdbuf -oL forces line-buffered output so tee flushes each line to the file immediately.
stdbuf -oL "${SPARK_HOME}/bin/spark-submit" \
  --class org.apache.spark.sql.connect.service.SparkConnectServer \
  --master "local[*]" \
  --conf spark.connect.grpc.binding.port=15002 \
  --conf spark.connect.grpc.arrow.maxBatchSize=134217728 \
  --conf spark.driver.memory="${SPARK_DRIVER_MEMORY:-4g}" \
  --conf spark.driver.host=127.0.0.1 \
  --conf spark.ui.enabled=false \
  "${SPARK_HOME}/jars/spark-connect_*.jar" 2>&1 | tee "${SPARK_LOG}" &

SPARK_PID=$!

# Signal Lambda Managed Instances that init is complete by calling /invocation/next.
# Per AWS docs: "the Init phase is complete when at least one runtime worker calls /next".
# We then keep long-polling /next so the instance stays alive.
if [[ -n "${AWS_LAMBDA_RUNTIME_API:-}" ]]; then
  # Wait for Spark Connect to bind port 15002.
  until grep -q "Spark Connect server started at" "${SPARK_LOG}" 2>/dev/null; do
    sleep 1
  done

  RUNTIME_API="http://${AWS_LAMBDA_RUNTIME_API}/2018-06-01/runtime"

  # Long-poll loop — each GET /invocation/next signals readiness and keeps the instance alive.
  while kill -0 $SPARK_PID 2>/dev/null; do
    RESPONSE=$(curl -sf "${RUNTIME_API}/invocation/next" 2>/dev/null || true)
    REQUEST_ID=$(echo "${RESPONSE}" | grep -o '"awsRequestId":"[^"]*"' | cut -d'"' -f4 || true)
    if [[ -n "${REQUEST_ID}" ]]; then
      # Managed Instances functions don't receive invocations in the normal sense;
      # ack any that do arrive so the runtime doesn't hang.
      curl -sf -X POST \
        "${RUNTIME_API}/invocation/${REQUEST_ID}/response" \
        -d '{"statusCode":200}' >/dev/null 2>&1 || true
    fi
  done
fi

wait $SPARK_PID
