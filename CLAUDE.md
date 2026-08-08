# Flashpoint

Serverless multi-node Apache Spark on AWS, with a Snowflake-equivalent UI. Spark Connect (gRPC) is
the client protocol.

## Tracking

The GitHub Project board is the single source of truth: https://github.com/users/prabodh1194/projects/3
- All work is an issue on the board, assigned to a milestone.
- Keep the board in sync — new work becomes an issue before it is worked.

## Milestones

| Milestone | Layer |
|-----------|-------|
| Ember | Storage + compute foundation (driver, executors, shuffle, benchmarks) |
| Kindle | Warehouse layer (manager, router, metering, warehouse sizing) |
| Forge | Catalog + multi-tenancy (Iceberg, Glue, IAM isolation) |
| Beacon | UI (worksheet, query-profile DAG, warehouse manager, data explorer) |

## Repo layout

```
infra/     OpenTofu IaC
driver/    Spark Connect server container + shuffle plugin
gateway/   warehouse manager, query router, profile DAG parsing (dag.py)
metering/  compute-second + cost accounting
catalog/   Glue/Iceberg integration
web/       Vite + React UI (no Tailwind — inline styles + CSS vars)
bench/     TPC-DS/TPC-H, cold-start + cost benchmarks
```

## Resolved decisions

- IaC: OpenTofu.
- Catalog: AWS Glue.
- Spark: stock Apache Spark Connect; fork only if a needed hook is unavailable via plugin.
- Compute: ECS Fargate (On-Demand for driver, Spot for executors).
- Routing: zero-dep hash router in `web/src/router.js` (`#/worksheets`, `#/warehouses`,
  `#/history`, `#/history/:queryId`, `#/explorer`). No react-router.
- Profile UI: every view has a URL; deep links are reload-safe.
- Profile cards: trivial details live on the card itself (scan → table + path, filter →
  WHERE predicate, join → type + qualified keys), not hidden behind a click.

## Coding standard

Clean Code (Robert C. Martin):
- Meaningful names; small single-responsibility functions; few arguments.
- No hidden side effects; command/query separation; DRY.
- Comments explain *why*, not *what*.
- SOLID at module boundaries.
- Tests first-class; TDD where practical.

### Data flow

**State lives in DynamoDB, not in Python dicts.** Every read goes through
`store.get_warehouse()`. Every write goes through `store.put/update/delete`.
No local mirrors, no dual-write, no in-memory caches for anything that must
survive a gateway restart or be visible to another gateway instance.

The gateway is stateless. If two instances can't agree on state by reading
DynamoDB, the design is wrong.

The only acceptable in-memory state: ephemeral convenience (e.g. the 500-entry
query history ring buffer, which is a disposable UX feature — the meters table
is the durable source).

### Query profile pipeline

`gateway/dag.py` pulls the Spark UI's execution detail, parses metrics and the
plan text into `{nodes, edges}`: per-node duration/task breakdown, column
treatments, scan location, filter conditions. The UI (`web/src/components/QueryDag.jsx`)
renders it as a result-at-top tree — joins fan out side-by-side, and
WholeStageCodegen wrappers become slim stage chips.

Review every diff against these before committing.
