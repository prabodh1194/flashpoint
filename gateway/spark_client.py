"""Spark Connect client cache — one SparkSession per name."""
import logging
from pyspark.sql import SparkSession

log = logging.getLogger(__name__)

_cache: dict[str, SparkSession] = {}


def get(endpoint: str, name: str) -> SparkSession:
    if name not in _cache:
        _cache[name] = (
            SparkSession.builder.remote(endpoint).getOrCreate()
        )
    return _cache[name]


def drop(name: str) -> None:
    spark = _cache.pop(name, None)
    if spark:
        try:
            spark.stop()
        except Exception:
            pass
