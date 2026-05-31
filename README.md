# Flashpoint

Serverless multi-node Apache Spark on AWS, with a Snowflake-equivalent UI. Clients connect over
Spark Connect (gRPC).

## Architecture

```
Client (SQL / DataFrame)
   │ gRPC (Spark Connect)
Gateway            session routing, auth        (stateless Lambda)
   │
Spark driver       Lambda Managed Instances     (container)
   │
Executors          Lambda Managed Instances     (auto-scaled)
   │
Shuffle            local NVMe → async flush → S3 Files
   │
Tables             Iceberg on S3 Files, catalog in AWS Glue
```

Shuffle approach: write to local NVMe, async-flush to S3 Files for durability; recover from S3 Files
on executor loss instead of recomputing.

## Status

Pre-implementation. Tracking: https://github.com/users/prabodh1194/projects/3

| Milestone | Scope |
|-----------|-------|
| Ember | Driver, multi-node executors, hybrid shuffle, Snowflake benchmark |
| Kindle | Session manager, router, metering, warehouse sizing |
| Forge | Iceberg, Glue catalog, IAM tenant isolation |
| Beacon | UI: worksheet, query-profile DAG, warehouse manager, data explorer |

## Key dependencies

- Lambda Managed Instances (GA Nov 2025): EC2-backed Lambda compute, container support, warm
  minimum (no scale-to-zero).
- S3 Files (2026): NFS v4.1/4.2 over S3, built on EFS.
- Apache Spark Connect: gRPC client/server protocol.

## Related work

- DataFlint — Spark UI plugin; partly commercial; no serverless layer.
- Delight (Data Mechanics) — Spark monitoring UI; inactive since 2022.
- EMR Serverless / GCP Serverless Spark — managed Spark; no standalone UI; cloud-specific.

## License

MIT
