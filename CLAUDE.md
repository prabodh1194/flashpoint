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
| Kindle | Session layer (manager, router, metering, warehouse sizing) |
| Forge | Catalog + multi-tenancy (Iceberg, Glue, IAM isolation) |
| Beacon | UI (worksheet, query-profile DAG, warehouse manager, data explorer) |

## Repo layout

```
infra/     OpenTofu IaC
driver/    Spark Connect server container + shuffle plugin
gateway/   session manager, query router
metering/  compute-second + cost accounting
catalog/   Glue/Iceberg integration
web/        Vite + React + Tailwind UI
bench/     TPC-DS/TPC-H, cold-start + cost benchmarks
```

## Resolved decisions

- IaC: OpenTofu.
- Catalog: AWS Glue.
- Spark: stock Apache Spark Connect; fork only if a needed hook is unavailable via plugin.
- Compute: Lambda Managed Instances (EC2-backed, container, warm minimum, no scale-to-zero).

## Coding standard

Clean Code (Robert C. Martin):
- Meaningful names; small single-responsibility functions; few arguments.
- No hidden side effects; command/query separation; DRY.
- Comments explain *why*, not *what*.
- SOLID at module boundaries.
- Tests first-class; TDD where practical.

Review every diff against these before committing.
