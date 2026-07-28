"""Spark Connect client cache — one SparkSession per warehouse_id."""
import logging
from pyspark.sql import SparkSession

log = logging.getLogger(__name__)

_cache: dict[str, SparkSession] = {}


def get(endpoint: str, warehouse_id: str) -> SparkSession:
    if warehouse_id not in _cache:
        _cache[warehouse_id] = (
            SparkSession.builder.remote(endpoint).getOrCreate()
        )
    return _cache[warehouse_id]


def drop(warehouse_id: str) -> None:
    spark = _cache.pop(warehouse_id, None)
    if spark:
        try:
            spark.stop()
        except Exception:
            pass
