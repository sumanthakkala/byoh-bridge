"""SubscriptionRegistry — which browser tabs want which tables' change events (PRD-04).

In-memory; rebuilt on reconnect (the browser re-sends ``byo.db.subscribe`` after
``relay.hello``). ``byo.db.subscribe`` REPLACES a browser's set, so the browser
just sends its current union of interests.
"""

from __future__ import annotations

from threading import Lock


class SubscriptionRegistry:
    def __init__(self) -> None:
        self._subs: dict[str, set[str]] = {}
        self._lock = Lock()

    def set(self, browser_session: str, tables: list[str]) -> None:
        """Replace this browser's subscribed tables."""
        with self._lock:
            if tables:
                self._subs[browser_session] = set(tables)
            else:
                self._subs.pop(browser_session, None)

    def drop(self, browser_session: str) -> None:
        with self._lock:
            self._subs.pop(browser_session, None)

    def browsers_for(self, table: str) -> list[str]:
        with self._lock:
            return [bs for bs, tables in self._subs.items() if table in tables or "*" in tables]
