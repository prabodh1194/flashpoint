"""Spark Connect client cache — one SparkSession per session_id."""
import logging
from pyspark.sql import SparkSession

log = logging.getLogger(__name__)

_cache: dict[str, SparkSession] = {}


def get(endpoint: str, session_id: str) -> SparkSession:
    if session_id not in _cache:
        _cache[session_id] = (
            SparkSession.builder.remote(endpoint).getOrCreate()
        )
    return _cache[session_id]


def drop(session_id: str) -> None:
    spark = _cache.pop(session_id, None)
    if spark:
        try:
            spark.stop()
        except Exception:
            pass
