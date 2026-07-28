# Flashpoint

Serverless multi-node Apache Spark on AWS, with a Snowflake-equivalent UI. Clients connect over
Spark Connect (gRPC).

## Architecture

```
Client (SQL / DataFrame)
   │ gRPC (Spark Connect)
Gateway            warehouse routing, auth, HA    (EC2, stateless)
   │
Spark driver       ECS Fargate                  (container)
   │
Executors          ECS Fargate                  (auto-scaled)
   │
Shuffle            local ephemeral → async flush → S3 Files
   │
State              DynamoDB (warehouse + warehouse metadata)
   │
Tables             Iceberg on S3 Files, catalog in AWS Glue
```

Shuffle approach: write to local ephemeral storage, async-flush to S3 Files for durability; recover
from S3 Files on executor loss instead of recomputing.

## Status

Actively developing. Tracking: https://github.com/users/prabodh1194/projects/3

| Milestone | Scope |
|-----------|-------|
| Ember | Driver, multi-node executors, hybrid shuffle, Snowflake benchmark |
| Kindle | Warehouse manager, router, metering, warehouse sizing |
| Forge | Iceberg, Glue catalog, IAM tenant isolation |
| Beacon | UI: worksheet, query-profile DAG, warehouse manager, data explorer |

## Key dependencies

- ECS Fargate: serverless container compute for driver and executors.
- S3 Files: NFS v4.1/4.2 over S3 for shuffle persistence.
- DynamoDB: warehouse state and warehouse configuration.
- Apache Spark Connect: gRPC client/server protocol.
- OpenTofu: infrastructure-as-code for all AWS resources.

## Related work

- DataFlint — Spark UI plugin; partly commercial; no serverless layer.
- Delight (Data Mechanics) — Spark monitoring UI; inactive since 2022.
- EMR Serverless / GCP Serverless Spark — managed Spark; no standalone UI; cloud-specific.

## License

MIT
