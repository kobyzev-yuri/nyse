"""
Уровень 2: ``cheap_sentiment`` в диапазоне [−1, 1].

Приоритет:
1. ``NewsArticle.raw_sentiment`` с API (Marketaux, Alpha Vantage и т.д.) — копируется с обрезкой;
2. иначе локальная модель HuggingFace (``SENTIMENT_MODEL``, по умолчанию FinBERT), если
   ``NYSE_SENTIMENT_LOCAL`` не выключен и установлен пакет ``transformers``;
3. иначе **0.0** (нейтрально).

Опционально: ``FileCache`` по ключу ``hash(модель + текст)`` (TTL ``NYSE_SENTIMENT_CACHE_TTL_SEC``).
"""

from __future__ import annotations

import hashlib
import logging
import re as _re
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Optional

from domain import NewsArticle

from .cache import FileCache

logger = logging.getLogger(__name__)

# HuggingFace pipeline кешируется по id модели — избегаем повторной загрузки весов
# (аналогично lse/services/sentiment_analyzer.py).
_pipelines: dict[str, object] = {}

# ---------------------------------------------------------------------------
# Паттерны движения цены в заголовке (price_pattern_boost)
# ---------------------------------------------------------------------------

_PRICE_MOVE_RE = _re.compile(
    r"""
    (?P<verb>
        jump(?:s|ed)?|surge(?:s|d)?|soar(?:s|ed)?|rocket(?:s|ed)?|rally|rallies|rallied|
        gain(?:s|ed)?|rise(?:s)?|rose|climb(?:s|ed)?|advance(?:s|d)?|up|
        drop(?:s|ped)?|fall(?:s)?|fell|sink(?:s|ing)?|sank|slide(?:s|d)?|plunge(?:s|d)?|
        crash(?:es|ed)?|tumble(?:s|d)?|decline(?:s|d)?|lose(?:s)?|lost|down
    )
    \s+
    (?P<pct>\d+(?:\.\d+)?)
    \s*%
    """,
    _re.VERBOSE | _re.IGNORECASE,
)

_BEARISH_VERBS = frozenset(
    "drop drops dropped fall falls fell sink sinks sinking sank slide slides slid "
    "plunge plunges plunged crash crashes crashed tumble tumbles tumbled "
    "decline declines declined lose loses lost down".split()
)


def price_pattern_boost(title: str) -> Optional[float]:
    """
    Ищет в заголовке паттерн движения цены («jumped 15%», «sinks 4%» и т.д.).
    Возвращает ориентированный сигнал в диапазоне [−1, 1] или ``None`` если
    паттерн не найден.

    Логика масштабирования:
        pct ≥ 20 → ±1.0
        pct ≥ 10 → ±0.8
        pct ≥  5 → ±0.6
        pct ≥  2 → ±0.4
        иначе    → ±0.2
    """
    m = _PRICE_MOVE_RE.search(title)
    if not m:
        return None
    pct = float(m.group("pct"))
    verb = m.group("verb").lower().rstrip("s").rstrip("ed").rstrip("d")
    negative = verb in _BEARISH_VERBS or m.group("verb").lower() in _BEARISH_VERBS

    if pct >= 20:
        magnitude = 1.0
    elif pct >= 10:
        magnitude = 0.8
    elif pct >= 5:
        magnitude = 0.6
    elif pct >= 2:
        magnitude = 0.4
    else:
        magnitude = 0.2

    return -magnitude if negative else magnitude


def article_text(article: NewsArticle, max_chars: int = 4000) -> str:
    """Текст для модели: заголовок и краткое описание."""
    parts = [article.title.strip()]
    if article.summary and article.summary.strip():
        parts.append(article.summary.strip())
    return "\n".join(parts)[:max_chars]


def _clip_minus1_1(x: float) -> float:
    return max(-1.0, min(1.0, float(x)))


def _local_sentiment_01(text: str, model_name: str) -> float:
    """
    Локальная модель: оценка в [0, 1] (0 = негатив, 0.5 = нейтраль, 1 = позитив), как в lse.
    При ошибке или пустом тексте — 0.5.
    """
    if not text or not text.strip():
        return 0.5
    t = text.strip()[:4000]
    try:
        from transformers import pipeline
    except ImportError:
        logger.warning("transformers не установлен — локальный sentiment недоступен")
        return 0.5

    global _pipelines
    if model_name not in _pipelines:
        _pipelines[model_name] = pipeline(
            "text-classification",
            model=model_name,
            top_k=None,
            truncation=True,
            max_length=512,
        )
    pipe = _pipelines[model_name]
    out = pipe(t[:512])
    if not out:
        return 0.5
    preds = out[0] if isinstance(out, list) else out
    if isinstance(preds, dict):
        best = preds
    elif isinstance(preds, list) and len(preds) > 0:
        best = max(
            preds,
            key=lambda x: x.get("score", 0) if isinstance(x, dict) else 0,
        )
    else:
        return 0.5
    label = (best.get("label") or "").lower()
    score = float(best.get("score", 0.5))
    if "neg" in label or label == "negative":
        sentiment = 1.0 - score
    elif "pos" in label or label == "positive":
        sentiment = score
    else:
        sentiment = 0.5
    return max(0.0, min(1.0, sentiment))


def local_sentiment_minus1_to_1(text: str, *, model_name: str) -> float:
    """0..1 → −1..1 (нейтраль 0.5 → 0.0)."""
    s01 = _local_sentiment_01(text, model_name)
    return 2.0 * s01 - 1.0


def _cache_key(model: str, text: str) -> str:
    h = hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()
    return f"cheap_sentiment|{h}"


def resolve_cheap_sentiment(
    article: NewsArticle,
    *,
    use_local: bool = True,
    model_name: str | None = None,
    cache: Optional[FileCache] = None,
) -> float:
    import config_loader

    model = (model_name or config_loader.get_sentiment_model_name()).strip() or "ProsusAI/finbert"

    if article.raw_sentiment is not None:
        return _clip_minus1_1(float(article.raw_sentiment))

    text = article_text(article)
    cache_key = _cache_key(model, text) if text.strip() else None

    if cache is not None and cache_key:
        hit = cache.get(cache_key)
        if hit is not None:
            try:
                return _clip_minus1_1(float(hit))
            except (TypeError, ValueError):
                pass

    if not use_local or not text.strip():
        result = 0.0
    else:
        try:
            result = local_sentiment_minus1_to_1(text, model_name=model)
        except Exception as e:
            logger.warning("Локальный sentiment: %s", e)
            result = 0.0

    result = _clip_minus1_1(result)

    # Если FinBERT дал слабый сигнал, но в заголовке явное ценовое движение —
    # используем паттерн как нижнюю границу силы сигнала (сохраняем направление).
    boost = price_pattern_boost(article.title)
    if boost is not None and abs(boost) > abs(result):
        result = boost

    if cache is not None and cache_key:
        ttl = config_loader.sentiment_cache_ttl_sec()
        cache.set(cache_key, result, ttl_sec=ttl)
    return result


def enrich_cheap_sentiment(
    articles: List[NewsArticle],
    *,
    use_local: bool | None = None,
    model_name: str | None = None,
    cache: Optional[FileCache] = None,
) -> List[NewsArticle]:
    """
    Возвращает новые ``NewsArticle`` с заполненным ``cheap_sentiment`` (не мутирует вход).
    ``use_local``: по умолчанию из ``NYSE_SENTIMENT_LOCAL`` / ``config_loader.sentiment_local_enabled()``.
    """
    import config_loader

    ul = config_loader.sentiment_local_enabled() if use_local is None else use_local
    out: List[NewsArticle] = []
    for a in articles:
        score = resolve_cheap_sentiment(
            a,
            use_local=ul,
            model_name=model_name,
            cache=cache,
        )
        out.append(replace(a, cheap_sentiment=score))
    return out


def default_sentiment_cache_dir() -> Path:
    """Каталог по умолчанию для файлового кэша сентимента (под ./.cache/nyse/sentiment)."""
    return Path.cwd() / ".cache" / "nyse" / "sentiment"


def enrich_with_default_cache(
    articles: List[NewsArticle],
    *,
    use_local: bool | None = None,
    model_name: str | None = None,
    cache_root: Path | None = None,
) -> List[NewsArticle]:
    """Обёртка: создаёт ``FileCache`` в ``cache_root`` или ``default_sentiment_cache_dir()``."""
    import config_loader

    root = cache_root or default_sentiment_cache_dir()
    ttl = config_loader.sentiment_cache_ttl_sec()
    fc = FileCache(root, default_ttl_sec=ttl)
    return enrich_cheap_sentiment(
        articles,
        use_local=use_local,
        model_name=model_name,
        cache=fc,
    )
