# Flashpoint

Snowflake-equivalent analytics warehouse on Apache Spark Connect. Clients submit SQL over
REST; compute runs as serverless multi-node Spark on AWS; the UI delivers the Snowflake
experience — warehouse lifecycle, worksheets, query-profile DAG, data explorer, cost center.

## Scope — the product loop

Create a warehouse → run SQL → inspect the query profile → pay per compute-second.
Every component serves that loop.

## Workflow — board first

The GitHub Project board is the single source of truth:
https://github.com/users/prabodh1194/projects/3

- All work is an issue on the board, assigned to a milestone.
- New work becomes an issue before it is worked.
- Keep the board in sync as work lands.

| Milestone | Layer | Scope |
|---|---|---|
| Ember | Storage + compute | driver, executors, shuffle, benchmarks |
| Kindle | Warehouse layer | manager, router, metering, warehouse sizing |
| Forge | Catalog + multi-tenancy | Iceberg, Glue, IAM isolation |
| Beacon | UI | worksheet, profile DAG, warehouse manager, explorer, cost center |

## Repo map

Each component directory has its own AGENTS.md. Read it before touching that component.

| Path | What | Context |
|---|---|---|
| `gateway/` | EC2 control plane: warehouse lifecycle, query dispatch, metering, cost center, profile parsing | `gateway/AGENTS.md` |
| `driver/` | Spark Connect server container (driver + executor roles) | `driver/AGENTS.md` |
| `web/` | Vite + React UI | `web/AGENTS.md` |
| `infra/` | OpenTofu AWS stack | `infra/AGENTS.md` |
| `scripts/` | local e2e demo and teardown | `scripts/AGENTS.md` |
| `docs/` | ADRs, deep dives, static product pages | — |

## Architecture

```
Client (SQL / DataFrame)
   │ REST
Gateway (EC2, stateless, FastAPI :8080)
   │ Spark Connect gRPC
Driver (ECS Fargate on-demand, 4 vCPU / 16 GB, SparkConnectServer :15002, UI :4040)
   │ Spark Standalone master :7077
Executors ×N (ECS Fargate Spot, 2 vCPU / 8 GB each)
   │
Tables  Iceberg on S3, catalog in Glue
State   DynamoDB (warehouses, meters, queries)
Results S3 query-results bucket, 7-day expiry
```

Spark Connect clients (notebooks, DataFrame code) can also connect straight to a warehouse's
gRPC endpoint (`sc://<driver-ip>:15002`); the REST gateway is the control plane and SQL path.

## Invariants

- State lives in DynamoDB, not Python dicts. Every read goes through `store.get_*`, every
  write through `store.put_*` / `update_*` / `delete_*`. No in-memory mirrors, no dual
  writes. The gateway is stateless: two instances must agree by reading DynamoDB. The only
  allowed in-memory state is disposable UX (the 500-entry query-history ring buffer); the
  meters table is durable.
- Spark Connect is the only client protocol. The gateway's `pyspark` pin, the driver image,
  and `driver/pyproject.toml` all stay on the same Spark version.
- Every UI view has a URL; hash routes reload safely.
- Money paths (metering, rates, budget, cost series) have one source of truth:
  `gateway/config.py` and `gateway/cost_data.py`.

## Coding standard

Clean Code: meaningful names; small single-responsibility functions; few arguments; no
hidden side effects; command/query separation; DRY. Comments explain why, not what. Tests
are first-class; TDD where practical.

## Commands

| Task | Command |
|---|---|
| Local e2e (laptop, AWS mocked) | `python3 scripts/e2e_demo.py` |
| Gateway tests | `cd gateway && uv run pytest` |
| Gateway lint / format / types | `cd gateway && uv run ruff check . && uv run ruff format . && uv run ty check` |
| Web dev server | `cd web && npm run dev` |
| Web lint / build | `cd web && npm run lint && npm run build` |
| Infra plan / apply | `cd infra && tofu plan -var-file=dev.tfvars` |
| Teardown, zero-spend verify | `scripts/teardown.sh` |

## Docs

`docs/code-flow.md` traces a request end to end. `docs/adr-*.md` record resolved
decisions. `docs/quickstart.html` and `docs/deploy.html` are the local-run and AWS deploy
guides. Update docs when a decision or flow changes. IP working notes (`docs/ip-*.md`) stay
uncommitted and gitignored: this repo is public, and publishing a mechanism before a filing
decision is self-disclosed prior art.
