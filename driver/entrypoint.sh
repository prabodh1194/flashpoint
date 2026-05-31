#!/usr/bin/env bash
set -euo pipefail

exec "${SPARK_HOME}/bin/spark-submit" \
  --class org.apache.spark.sql.connect.service.SparkConnectServer \
  --master "local[*]" \
  --conf spark.connect.grpc.binding.port=15002 \
  --conf spark.connect.grpc.arrow.maxBatchSize=134217728 \
  --conf spark.driver.memory="${SPARK_DRIVER_MEMORY:-4g}" \
  --conf spark.ui.enabled=false \
  "${SPARK_HOME}/jars/spark-connect_*.jar"
