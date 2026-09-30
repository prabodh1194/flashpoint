# Gateway

FastAPI control plane on EC2 (`:8080`). Stateless; DynamoDB is the single source of truth.
Owns warehouse lifecycle, query dispatch over Spark Connect, metering, cost center, and
query-profile parsing. Milestones: Kindle (warehouse layer), Beacon (profile + cost APIs).

Imports are flat siblings — run from `gateway/` (`uv run pytest` sets `pythonpath = ["."]`).

## Modules

| File | Role |
|---|---|
| `main.py` | app wiring, startup reconcile, idle-warehouse reaper |
| `config.py` | env vars, sizes, hourly rates, timeouts, monthly budget |
| `models.py` | Pydantic request/response models |
| `store.py` | DynamoDB access: warehouses, queries, atomic claim, counts |
| `routes_warehouses.py` | warehouse CRUD + suspend/resume/resize |
| `routes_queries.py` | sync + async queries, cancel, `/queries/*`, `/history` |
| `routes_costs.py` | `/resources`, `/costs` — Cost Center |
| `cost_data.py` | AWS resource inventory + daily cost series |
| `ecs_tasks.py` | ECS RunTask/StopTask for driver + executors |
| `spark_client.py` | one cached SparkSession per warehouse; tags and interrupts |
| `query_runner.py` | async query: Spark → Parquet → S3 → DynamoDB |
| `dag.py` | Spark UI REST (`:4040`) → `{nodes, edges}` query profile |
| `meters.py` | compute-second metering into DynamoDB |
| `reconcile.py` | orphan-task cleanup + idle-TTL suspend |
| `state.py` | ephemeral query-history ring buffer + `QueryStatus` |
| `local_dev.py` | AWS-mocked local server; entry point for `scripts/e2e_demo.py` |

## API surface

- `POST /warehouses`, `GET /warehouses`, `GET|DELETE /warehouses/{name}`
- `POST /warehouses/{name}/suspend|resume|resize`
- `POST /warehouses/{name}/query` (sync), `/query/async`, `/query/cancel`
- `GET /queries/{id}`, `GET /queries/{id}/result`
- `GET /history`, `DELETE /history`, `GET /history/{id}`
- `GET /resources`, `GET /costs?days=N`, `GET /healthz`

## Rules

- State in DynamoDB only. Never cache warehouse state in module globals.
- Create is atomic: `put_warehouse_if_absent` claims the name with a conditional PutItem;
  a launch failure stops orphan tasks and deletes the record. `MAX_WAREHOUSES` (default 3)
  caps concurrently running warehouses.
- Sync queries run on a daemon thread bounded by `QUERY_TIMEOUT_S` (300s); on timeout call
  `spark_client.interrupt(name, qid)` and return 504. Never let a wedged driver block the
  API thread.
- Async query IDs are content-addressed (`sql` + warehouse `created_at`) so a resubmit is a
  cache hit; records carry a `ttl` and expire after `QUERY_RESULT_TTL_DAYS`.
- `pyspark` is pinned to the driver image's Spark version — bump both together.
- `local_dev.py` patches `boto3` and the ECS helpers before importing app modules; keep its
  imports below the patches. It substitutes deterministic fixtures for Cost Center data.
- Metering starts at name-claim time (`session_started_at`), not at task RUNNING.

## Tests

`cd gateway && uv run pytest`. `tests/conftest.py` sets env vars and MagicMock-based AWS
stubs; `tests/test_routes.py` and `tests/test_store.py` are the anchors. Lint:
`uv run ruff check .`; types: `uv run ty check`. Add a test for every route or store
behavior change.
