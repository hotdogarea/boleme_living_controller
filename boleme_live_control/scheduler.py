"""Deterministic, single-session schedules for on-air actions."""

from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True)
class Phrase:
    text: str
    interval: int = 120


@dataclass(frozen=True)
class Product:
    number: int
    repeats: int = 1
    interval: int = 60


class SequenceScheduler:
    def __init__(self, items, clock=monotonic):
        self.items = list(items)
        self.clock = clock
        self.index = 0
        self.remaining = 0
        self.next_at = self.clock()

    def due(self):
        if not self.items or self.clock() < self.next_at:
            return None
        item = self.items[self.index]
        if not self.remaining:
            self.remaining = max(1, getattr(item, "repeats", 1))
        self.remaining -= 1
        if not self.remaining:
            self.index = (self.index + 1) % len(self.items)
        self.next_at = self.clock() + max(1, item.interval)
        return item
