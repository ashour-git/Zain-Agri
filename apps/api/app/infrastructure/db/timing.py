"""Per-request database timing: new connections and query time.

The request middleware calls ``start()`` and reads the totals after the
response is built. Engine events fill them in. A request's handler runs in a
child task that copies the context, so it sees (and mutates) the same
``DbTiming`` object the middleware created.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

_QUERY_STARTS = "zain_query_starts"


@dataclass
class DbTiming:
    connect_ms: float = 0.0
    connects: int = 0
    query_ms: float = 0.0
    queries: int = 0
    _connect_started: float | None = None


_current: ContextVar[DbTiming | None] = ContextVar("zain_db_timing", default=None)


def start() -> DbTiming:
    timing = DbTiming()
    _current.set(timing)
    return timing


def install(engine: Engine) -> None:
    """Attach the timing listeners to a (sync) engine. Call once per engine."""

    @event.listens_for(engine, "do_connect")
    def _before_connect(*_args: Any) -> None:
        timing = _current.get()
        if timing is not None:
            timing._connect_started = time.perf_counter()

    @event.listens_for(engine, "connect")
    def _after_connect(*_args: Any) -> None:
        timing = _current.get()
        if timing is not None and timing._connect_started is not None:
            timing.connect_ms += (time.perf_counter() - timing._connect_started) * 1000
            timing.connects += 1
            timing._connect_started = None

    @event.listens_for(engine, "before_cursor_execute")
    def _before_query(conn: Any, *_args: Any) -> None:
        conn.info.setdefault(_QUERY_STARTS, []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after_query(conn: Any, *_args: Any) -> None:
        starts = conn.info.get(_QUERY_STARTS)
        timing = _current.get()
        if starts and timing is not None:
            timing.query_ms += (time.perf_counter() - starts.pop()) * 1000
            timing.queries += 1
