"""Батчи списков — как ``pystockinvest/agent/utils.py::chunked``."""

from __future__ import annotations

from typing import Iterable, List, Optional, TypeVar

T = TypeVar("T")


def chunked(items: List[T], batch_size: Optional[int]) -> Iterable[List[T]]:
    if batch_size is None:
        yield items
        return

    if batch_size <= 0:
        raise ValueError("batch_size must be positive or None")

    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]
