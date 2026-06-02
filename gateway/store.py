"""DynamoDB-backed session store — the durable replacement for the in-memory sessions dict.

All writes go to DynamoDB first; the in-memory cache in main.py is rebuilt from DynamoDB on
startup via reconcile(). Keeping the two stores consistent is the responsibility of the callers
in main.py — every path that mutates a session (create, suspend, resume, resize, delete, reap)
must call store.py before updating the local dict.
"""
import os
import time
from decimal import Decimal, ROUND_HALF_UP

import boto3

_TABLE_NAME = os.environ.get("FLASHPOINT_SESSIONS_TABLE", "flashpoint-dev-sessions")
_dynamodb = boto3.resource("dynamodb")


def _table():
    return _dynamodb.Table(_TABLE_NAME)


# --- Decimal/float conversion ---
# DynamoDB stores numbers as Decimal; float is not supported. Centralised here so
# created_at / cost_usd / etc. round-trip without precision drift.

def _to_ddb(v):
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, list):
        return [_to_ddb(i) for i in v]
    if isinstance(v, dict):
        return {k: _to_ddb(val) for k, val in v.items()}
    return v


def _from_ddb(v):
    if isinstance(v, Decimal):
        f = float(v)
        return int(f) if f == int(f) else f
    if isinstance(v, list):
        return [_from_ddb(i) for i in v]
    if isinstance(v, dict):
        return {k: _from_ddb(val) for k, val in v.items()}
    return v


# --- Commands ---

def put_session(session_id: str, item: dict) -> None:
    """Write (or overwrite) a complete session record to DynamoDB."""
    record = {"session_id": session_id, "updated_at": Decimal(str(time.time()))}
    record.update(_to_ddb(item))
    _table().put_item(Item=record)


def update_session_status(session_id: str, status: str, **extra) -> None:
    """Update status + optional extra fields without overwriting the whole record."""
    expr_parts = ["#st = :status", "updated_at = :ts"]
    names = {"#st": "status"}
    values = {":status": status, ":ts": Decimal(str(time.time()))}
    for k, v in extra.items():
        expr_parts.append(f"#{k} = :{k}")
        names[f"#{k}"] = k
        values[f":{k}"] = _to_ddb(v)
    _table().update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def delete_session(session_id: str) -> None:
    """Remove a session record from DynamoDB permanently."""
    _table().delete_item(Key={"session_id": session_id})


# --- Queries ---

def get_session(session_id: str) -> dict | None:
    resp = _table().get_item(Key={"session_id": session_id})
    item = resp.get("Item")
    return _from_ddb(item) if item else None


def list_sessions() -> list[dict]:
    resp = _table().scan()
    return [_from_ddb(item) for item in resp.get("Items", [])]
