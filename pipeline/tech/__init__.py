from __future__ import annotations

"""
Tech subpackage (L2).

Этап 1 миграции: новые импорты ``pipeline.tech.*`` ведут в существующий пакет
``pipeline.technical`` (без переносов файлов и без поломок).
"""

from ..technical import *  # noqa: F401,F403
