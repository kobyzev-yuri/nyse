from __future__ import annotations

"""
Trade subpackage (L6).

Этап 1 миграции: новые импорты ``pipeline.trade.*`` ведут в существующий модуль
``pipeline.trade_builder`` (без переносов файла и без поломок).
"""

from ..trade_builder import *  # noqa: F401,F403
