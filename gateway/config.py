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

# Hourly rate per warehouse size (USD) — driver + executors, on-demand ceiling.
# Single source of truth; the web UI reads it from the gateway.
HOURLY_RATE: dict[str, float] = {'XS': 0.08, 'S': 0.16, 'M': 0.32, 'L': 0.64, 'XL': 1.28}

# Monthly spend budget (USD) for the Cost Center projection warning.
MONTHLY_BUDGET_USD = float(os.environ.get('FLASHPOINT_MONTHLY_BUDGET', '20.0'))

# Sync-query deadline (seconds) — a hung driver must not wedge the API forever.
QUERY_TIMEOUT_S = int(os.environ.get('FLASHPOINT_QUERY_TIMEOUT_S', '300'))

METERS_TABLE = os.environ.get('FLASHPOINT_METERS_TABLE', 'flashpoint-dev-meters')
