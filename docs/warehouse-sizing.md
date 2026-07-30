# Warehouse Sizing

Driver does no data processing — query planning, scheduling, gRPC serving only.
Scales for concurrent user load, not query size. Heavy lift is on executors.

| Size | Driver (On-Demand) | Executor (Spot) | Execs | ~$/hr | ~$/mo (24/7) |
|------|-------------------|-----------------|-------|-------|---------------|
| XS   | 2vCPU / 4 GB   | 2vCPU / 8 GB   | 1  | $0.06 | $43  |
| S    | 2vCPU / 4 GB   | 2vCPU / 8 GB   | 2  | $0.10 | $72  |
| M    | 4vCPU / 8 GB   | 2vCPU / 8 GB   | 4  | $0.24 | $173 |
| L    | 4vCPU / 8 GB   | 4vCPU / 16 GB  | 4  | $0.34 | $245 |
| XL   | 4vCPU / 8 GB   | 4vCPU / 16 GB  | 8  | $0.56 | $403 |
| XXL  | 8vCPU / 16 GB  | 8vCPU / 32 GB  | 8  | $1.28 | $922 |
| XXXL | 8vCPU / 16 GB  | 8vCPU / 32 GB  | 16 | $2.25 | $1,620 |

Pricing: us-east-1 Fargate ARM (Graviton). On-demand: $0.04048/vCPU-hr + $0.004445/GB-hr.
Spot executors: ~70% discount on compute. EBS + S3 data transfer excluded.
Driver stays flat because it doesn't touch user data. Executors carry the load.
