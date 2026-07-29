"""Shared in-process state.

Ephemeral convenience only — the meters table is the durable source.
"""
from collections import deque

query_history: deque[dict] = deque(maxlen=500)
