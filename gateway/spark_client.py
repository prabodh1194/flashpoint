"""Spark Connect client cache — one SparkSession per name."""

import logging

from pyspark.sql import SparkSession

log = logging.getLogger(__name__)

_cache: dict[str, SparkSession] = {}


def get(endpoint: str, name: str) -> SparkSession:
    if name not in _cache:
        _cache[name] = SparkSession.builder.remote(endpoint).getOrCreate()  # ty: ignore
    return _cache[name]


def drop(name: str) -> None:
    spark = _cache.pop(name, None)
    if spark:
        try:
            spark.stop()
        except Exception:
            pass


def session_id(name: str) -> str | None:
    spark = _cache.get(name)
    if not spark:
        return None
    return getattr(spark, '_session_id', None)


def interrupt(name: str, qid: str | None = None) -> None:
    spark = _cache.get(name)
    if not spark:
        return
    try:
        if qid:
            spark.interruptTag(qid)
        else:
            spark.interruptAll()
    except Exception:
        pass
