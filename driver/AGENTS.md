# Driver

Spark Connect server container. One image serves both roles; `SPARK_ROLE` selects the path.
Spark 4.0.2 (Hadoop 3) on Temurin 17 JRE, ARM64.

## Roles

- `driver` (default): starts Spark Standalone master on `:7077`, waits for its UI on
  `:8080`, then submits `SparkConnectServer` on `:15002` with driver RPC `:7078` and block
  manager `:7337`. Spark UI on `:4040` — the gateway parses it for query profiles.
- `executor`: joins the driver's master as a worker using `SPARK_MASTER_URL`, cores and
  memory from `SPARK_EXECUTOR_CORES` / `SPARK_EXECUTOR_MEMORY`.

The container reads its IP from the ECS task metadata endpoint
(`ECS_CONTAINER_METADATA_URI_V4`), falling back to `127.0.0.1` locally. A fixed
`spark-driver` hostname is pre-registered in `/etc/hosts` so `InetAddress.getLocalHost()`
resolves inside Fargate.

## Files

| File | Role |
|---|---|
| `Dockerfile` | Temurin 17 JRE + Spark 4.0.2; exposes 15002/7077/8080/7078/7337/4040 |
| `entrypoint.sh` | role dispatch, IP discovery, master + Spark Connect launch |
| `smoke_test.py` | AC check: `spark.sql('select 1')` over `sc://HOST:PORT` |
| `pyproject.toml` | client deps for local smoke tests (`pyspark==4.0.2`) |

## Rules

- The Spark version in `Dockerfile` (`ARG SPARK_VERSION`), `driver/pyproject.toml`, and
  `gateway/pyproject.toml` must match. Bump all together; a mismatched client breaks the
  protocol.
- Publishing: build `linux/arm64` (Fargate tasks are ARM64), push to ECR, then update the
  image tag in `infra/ecs.tf` for both driver and executor task definitions.
- The stack is Spark Standalone under a Spark Connect server; keep the `spark://IP:7077`
  master URL in sync with `gateway/ecs_tasks.py`.

## Check

    python smoke_test.py <driver-ip> 15002
