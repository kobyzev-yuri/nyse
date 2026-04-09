from __future__ import annotations

"""
Подпакет news (L1–L5).

Этап 1 миграции: этот пакет даёт **новые** пути импорта вида ``pipeline.news.*``,
не ломая старые ``pipeline.*``. Реализация пока остаётся в корне ``pipeline/``;
``pipeline/news/*.py`` — тонкие re-export модули.
"""

