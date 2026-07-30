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
