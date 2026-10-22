"""Bounded per-process TTL/LRU cache; synchronous operations do not yield the event loop."""

import time
from collections import OrderedDict
from collections.abc import Callable


class SummaryCache:
    def __init__(self, ttl: float, max_entries: int, clock: Callable[[], float] = time.monotonic):
        self.ttl = ttl
        self.max_entries = max_entries
        self.clock = clock
        self._entries: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def _expire(self) -> None:
        now = self.clock()
        for key in [key for key, (expires, _) in self._entries.items() if expires <= now]:
            del self._entries[key]

    def get(self, key: str) -> str | None:
        self._expire()
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return entry[1]

    def set(self, key: str, summary: str) -> None:
        self._expire()
        if self.ttl == 0:
            return
        self._entries[key] = (self.clock() + self.ttl, summary)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
