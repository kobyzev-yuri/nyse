"""
Загрузка настроек для nyse: переменные окружения и опционально config.env.

Приоритет: уже установленные os.environ → файл из NYSE_CONFIG_PATH → ./config.env
→ при отсутствии: `../lse/config.env` относительно корня репозитория nyse (удобно в монорепо).

Тесты: по умолчанию **не** требуют config.env; интеграционные тесты с LLM помечайте и
пропускайте без ключа (см. tests/conftest.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def _apply_env(overrides: dict[str, str]) -> None:
    for k, v in overrides.items():
        if k not in os.environ or os.environ.get(k, "") == "":
            os.environ[k] = v


def load_config_env() -> None:
    """
    Подмешивает значения из файла в os.environ (не перезаписывает уже заданные переменные).
    """
    path = config_env_path()
    _apply_env(_parse_env_file(path))


def config_env_path() -> Path:
    """Путь к файлу с секретами для загрузки."""
    explicit = os.environ.get("NYSE_CONFIG_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    local = _REPO_ROOT / "config.env"
    if local.is_file():
        return local
    fallback = _REPO_ROOT.parent / "lse" / "config.env"
    return fallback


@dataclass(frozen=True)
class OpenAISettings:
    api_key: str
    base_url: str
    model: str
    temperature: float
    timeout_sec: int


def get_openai_settings() -> Optional[OpenAISettings]:
    """None, если нет ключа — вызывать load_config_env() заранее при необходимости."""
    load_config_env()
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    return OpenAISettings(
        api_key=key,
        base_url=(
            os.environ.get("OPENAI_BASE_URL") or "https://api.proxyapi.ru/openai/v1"
        ).strip(),
        model=(os.environ.get("OPENAI_MODEL") or "gpt-4o").strip(),
        temperature=float(os.environ.get("OPENAI_TEMPERATURE") or "0"),
        timeout_sec=int(float(os.environ.get("OPENAI_TIMEOUT") or "60")),
    )


def get_config_value(key: str, default: Optional[str] = None) -> Optional[str]:
    load_config_env()
    return os.environ.get(key, default)


def get_newsapi_key() -> Optional[str]:
    """Ключ NewsAPI (newsapi.org); None, если не задан."""
    load_config_env()
    k = (os.environ.get("NEWSAPI_KEY") or "").strip()
    return k or None


def get_marketaux_api_key() -> Optional[str]:
    """Ключ Marketaux; None, если не задан."""
    load_config_env()
    k = (os.environ.get("MARKETAUX_API_KEY") or "").strip()
    return k or None


def get_alphavantage_api_key() -> Optional[str]:
    """Ключ Alpha Vantage (как в lse: ALPHAVANTAGE_KEY); None, если не задан."""
    load_config_env()
    k = (
        os.environ.get("ALPHAVANTAGE_KEY")
        or os.environ.get("ALPHAVANTAGE_API_KEY")
        or ""
    ).strip()
    return k or None


def get_sentiment_model_name() -> str:
    """HuggingFace id для локального сентимента (по умолчанию FinBERT)."""
    load_config_env()
    return (os.environ.get("SENTIMENT_MODEL") or "ProsusAI/finbert").strip()


def sentiment_local_enabled() -> bool:
    """Включить ли transformers при отсутствии raw_sentiment (по умолчанию да)."""
    load_config_env()
    raw = (os.environ.get("NYSE_SENTIMENT_LOCAL") or "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def sentiment_cache_ttl_sec() -> int:
    load_config_env()
    return int(float(os.environ.get("NYSE_SENTIMENT_CACHE_TTL_SEC") or "86400"))


def calendar_high_before_minutes() -> int:
    """За сколько минут до HIGH-события считать «скоро» (гейт C)."""
    load_config_env()
    return int(float(os.environ.get("NYSE_CALENDAR_HIGH_BEFORE_MIN") or "120"))


def calendar_high_after_minutes() -> int:
    """Сколько минут после HIGH-события ещё считать окно «скоро» (релиз прошёл)."""
    load_config_env()
    return int(float(os.environ.get("NYSE_CALENDAR_HIGH_AFTER_MIN") or "60"))


def nyse_cache_root() -> Path:
    """Корень файлового кэша nyse (по умолчанию ``./.cache/nyse``)."""
    load_config_env()
    raw = (os.environ.get("NYSE_CACHE_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(__file__).resolve().parent / ".cache" / "nyse"


def news_raw_cache_ttl_sec() -> int:
    """TTL списка статей с провайдера (сырьё)."""
    load_config_env()
    return int(float(os.environ.get("NYSE_NEWS_RAW_TTL_SEC") or "1800"))


def news_aggregate_cache_ttl_sec() -> int:
    """TTL закэшированного чернового импульса (агрегат)."""
    load_config_env()
    return int(float(os.environ.get("NYSE_NEWS_AGGREGATE_TTL_SEC") or "1800"))


def llm_cache_ttl_sec() -> int:
    """TTL ответов LLM (даджест / completion) в файловом кэше (этап F)."""
    load_config_env()
    return int(float(os.environ.get("NYSE_LLM_CACHE_TTL_SEC") or "86400"))


def use_llm_calendar_signal() -> bool:
    """Включить structured LLM для календаря (``NYSE_LLM_CALENDAR=1``)."""
    load_config_env()
    v = (os.environ.get("NYSE_LLM_CALENDAR") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def use_llm_technical_signal() -> bool:
    """Включить structured LLM для техники вместо эвристик (``NYSE_LLM_TECHNICAL=1``)."""
    load_config_env()
    v = (os.environ.get("NYSE_LLM_TECHNICAL") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def calendar_llm_batch_size() -> Optional[int]:
    """
    Размер батча событий для календарного LLM (как ``batch_size`` в pystockinvest ``agent/calendar``).
    None — все события в одном запросе.
    """
    load_config_env()
    raw = (os.environ.get("NYSE_CALENDAR_LLM_BATCH_SIZE") or "").strip()
    if not raw:
        return None
    try:
        n = int(raw)
        return n if n > 0 else None
    except ValueError:
        return None


def get_pipeline_gate_threshold():
    """
    Пороги гейта LLM (``ThresholdConfig``) для бота и прод-пайплайна.

    База — ``PROFILE_GAME5M`` из ``pipeline.types``; поля можно переопределить через
    ``NYSE_GATE_T1``, ``NYSE_GATE_T2``, ``NYSE_GATE_MAX_N``, ``NYSE_GATE_REGIME_STRESS_MIN``
    (см. ``config.env.example``). Некорректные значения игнорируются.
    """
    load_config_env()
    from pipeline.types import PROFILE_GAME5M, ThresholdConfig

    base = PROFILE_GAME5M

    def _opt_float(key: str, default: float) -> float:
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    def _opt_int(key: str, default: int) -> int:
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    return ThresholdConfig(
        t1_abs_draft_bias=_opt_float("NYSE_GATE_T1", base.t1_abs_draft_bias),
        t2_regime_confidence=_opt_float("NYSE_GATE_T2", base.t2_regime_confidence),
        max_articles_full_batch=_opt_int("NYSE_GATE_MAX_N", base.max_articles_full_batch),
        regime_stress_min=_opt_float(
            "NYSE_GATE_REGIME_STRESS_MIN", base.regime_stress_min
        ),
    )


# ============================================
# Tickers
# ============================================

_GAME5M_DEFAULT = "SNDK,NBIS,ASML,MU,LITE,CIEN"
_GAME5M_CONTEXT_DEFAULT = "QQQ,SMH"


def _parse_ticker_list(raw: str) -> list:
    """Парсит строку вида 'SNDK,NBIS,MU' → List[Ticker], пропуская неизвестные."""
    from domain import Ticker

    result = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.append(Ticker(part))
        except ValueError:
            try:
                result.append(Ticker[part])
            except KeyError:
                pass  # неизвестный тикер (^VIX, CL=F и т.п.) — пропускаем
    return result


def get_game5m_tickers() -> list:
    """
    Торговые тикеры GAME_5M из ``TICKERS_FAST`` в config.env.

    Используется во всех тестах и сигнальном цикле как приоритетный набор.
    Fallback: ``SNDK,NBIS,ASML,MU,LITE,CIEN``.
    """
    load_config_env()
    raw = (os.environ.get("TICKERS_FAST") or _GAME5M_DEFAULT).strip()
    return _parse_ticker_list(raw)


def get_game5m_context_tickers() -> list:
    """
    Контекстные тикеры для market_alignment (QQQ, SMH по умолчанию).
    """
    return _parse_ticker_list(_GAME5M_CONTEXT_DEFAULT)


# ============================================
# Telegram
# ============================================

def get_telegram_bot_token() -> Optional[str]:
    """Токен Telegram-бота (TELEGRAM_BOT_TOKEN); None, если не задан."""
    load_config_env()
    k = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    return k or None


def get_telegram_chat_id() -> Optional[str]:
    """
    Чат для сигналов.
    Берём первое значение из TELEGRAM_SIGNAL_CHAT_IDS или TELEGRAM_SIGNAL_CHAT_ID.
    None, если ни одно не задано.
    """
    load_config_env()
    ids = (os.environ.get("TELEGRAM_SIGNAL_CHAT_IDS") or "").strip()
    if ids:
        return ids.split(",")[0].strip() or None
    single = (os.environ.get("TELEGRAM_SIGNAL_CHAT_ID") or "").strip()
    return single or None


def get_telegram_proxy() -> Optional[str]:
    """
    Прокси для Telegram-бота (TELEGRAM_PROXY).
    Поддерживаемые форматы:
        socks5://user:pass@host:port
        http://host:port
        https://host:port
    None → прямое соединение.
    """
    load_config_env()
    v = (os.environ.get("TELEGRAM_PROXY") or "").strip()
    return v or None


def get_news_rss_feed_urls() -> list[str]:
    """
    URL RSS/Atom для ``sources.news_merge`` (переменная ``NYSE_NEWS_RSS_URLS``).
    Несколько адресов через запятую или с новой строки.
    """
    load_config_env()
    raw = (os.environ.get("NYSE_NEWS_RSS_URLS") or "").strip()
    if not raw:
        return []
    out: list[str] = []
    for line in raw.replace(",", "\n").splitlines():
        s = line.strip()
        if s:
            out.append(s)
    return out
