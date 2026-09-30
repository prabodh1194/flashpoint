"""Flashpoint gateway configuration — env vars and constants."""

import os

CLUSTER = os.environ['FLASHPOINT_ECS_CLUSTER']
TASK_DEF = os.environ['FLASHPOINT_DRIVER_TASK_DEF']
EXECUTOR_TASK_DEF = os.environ['FLASHPOINT_EXECUTOR_TASK_DEF']
SUBNETS = os.environ['FLASHPOINT_SUBNETS'].split(',')
SECURITY_GROUP = os.environ['FLASHPOINT_SECURITY_GROUP']
REGION = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
GRPC_PORT = int(os.environ.get('FLASHPOINT_GRPC_PORT', '15002'))
WAREHOUSE_TTL_S = int(os.environ.get('FLASHPOINT_WAREHOUSE_TTL_S', str(2 * 3600)))
MAX_WAREHOUSES = int(os.environ.get('FLASHPOINT_MAX_WAREHOUSES', '3'))
SPARK_UI_PORT = int(os.environ.get('FLASHPOINT_SPARK_UI_PORT', '4040'))

QUERY_RESULTS_BUCKET = os.environ.get(
    'FLASHPOINT_QUERY_RESULTS_BUCKET', 'flashpoint-dev-query-results'
)
QUERY_RESULT_TTL_DAYS = int(os.environ.get('FLASHPOINT_QUERY_RESULT_TTL_DAYS', '7'))

SIZES: dict[str, int] = {'XS': 1, 'S': 2, 'M': 4, 'L': 8, 'XL': 16}

# Verified us-east-1 ARM on-demand Fargate rates (Price List API, 2026-09-30).
# Driver task: 4 vCPU / 16 GB; executor task: 2 vCPU / 8 GB (infra/ecs.tf).
FARGATE_VCPU_H = 0.03238
FARGATE_GB_H = 0.00356
DRIVER_HOURLY_USD = 4 * FARGATE_VCPU_H + 16 * FARGATE_GB_H
EXECUTOR_HOURLY_USD = 2 * FARGATE_VCPU_H + 8 * FARGATE_GB_H

# Worst-case (executor on-demand) hourly cost per size — used by meters and the guard.
REAL_HOURLY_RATE: dict[str, float] = {
    size: DRIVER_HOURLY_USD + count * EXECUTOR_HOURLY_USD for size, count in SIZES.items()
}

# Spark-only monthly ceiling for the try-it deployment (docs/try-it-design.md §2.6).
# Fixed idle infra (~$16.50) is assumed spent before this envelope.
SPARK_BUDGET_USD = float(os.environ.get('FLASHPOINT_SPARK_BUDGET_USD', '3.00'))
SPARK_BUDGET_MARGIN_USD = float(os.environ.get('FLASHPOINT_SPARK_BUDGET_MARGIN_USD', '0.10'))

# Monthly spend budget (USD) for the Cost Center projection warning.
MONTHLY_BUDGET_USD = float(os.environ.get('FLASHPOINT_MONTHLY_BUDGET', '20.0'))

# Sync-query deadline (seconds) — a hung driver must not wedge the API forever.
QUERY_TIMEOUT_S = int(os.environ.get('FLASHPOINT_QUERY_TIMEOUT_S', '300'))

METERS_TABLE = os.environ.get('FLASHPOINT_METERS_TABLE', 'flashpoint-dev-meters')
