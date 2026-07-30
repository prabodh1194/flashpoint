"""Shared in-process state.

Ephemeral convenience only — the meters table is the durable source.
"""

from collections import deque
from enum import StrEnum

query_history: deque[dict] = deque(maxlen=500)


class QueryStatus(StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    DONE = 'done'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
