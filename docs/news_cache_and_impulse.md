# Кэш новостей, импульс и провайдеры

Документ фиксирует **реализованные решения** по кэшу, источникам и расчёту новостного импульса.  
Гипотезы закрыты; раздел «план» — только незакрытые задачи (Уровень 6, Telegram).

---

## 1. Кэш: реализованная схема

### Механизм: `FileCache` (без БД)

Единое хранилище — JSON-файлы в `.cache/nyse/`. Ни PostgreSQL, ни Redis не требуются.  
Подробное описание устройства, слоёв и TTL — в **`README.md § FileCache`**.

| Слой | Ключ (префикс) | TTL (env) | Значение |
|------|---------------|-----------|---------|
| Сырые новости | `raw\|v1\|provider\|ticker\|…` | `NYSE_NEWS_RAW_TTL_SEC` (900 с) | `NewsArticle[]` JSON |
| DraftImpulse | `draft\|v1\|ticker\|w…\|h…` | `NYSE_NEWS_AGGREGATE_TTL_SEC` (300 с) | `DraftImpulse` dict |
| Сентимент | `cheap_sentiment\|sha256(model+text)` | `NYSE_SENTIMENT_CACHE_TTL_SEC` (86400 с) | `float` |
| LLM-ответ | `llm\|v1\|prompt_ver\|model\|sha256(msgs)` | `NYSE_LLM_CACHE_TTL_SEC` (3600 с) | `str` (raw JSON) |

**Инвалидация:** поле `_expires_at` в каждом файле; проверяется лениво при чтении.  
**Корень:** `NYSE_CACHE_ROOT` (default: `.cache/nyse`).

### Реализованные фабрики

```python
from pipeline.news_cache import default_news_file_cache   # raw + draft
from pipeline.llm_cache  import default_llm_file_cache    # LLM-ответы
from pipeline.sentiment  import enrich_with_default_cache # сентимент
```

---

## 2. Провайдеры новостей: реализовано

| Провайдер | Модуль | Env-ключ | Что даёт |
|-----------|--------|---------|---------|
| Yahoo / yfinance | `sources/news.py` | — | Baseline: заголовки по тикеру |
| Marketaux | `sources/news_marketaux.py` | `MARKETAUX_API_KEY` | Статьи + entity + `raw_sentiment` |
| NewsAPI v2 | `sources/news_newsapi.py` | `NEWSAPI_KEY` | Тематические запросы по тикеру |
| Alpha Vantage | `sources/news_alphavantage.py` | `ALPHAVANTAGE_KEY` | NEWS_SENTIMENT endpoint |
| RSS/Atom | `sources/news_rss.py` | — (url в конфиге) | ЦБ, агентства, макро-ленты |

Все адаптеры нормализуют вход в `NewsArticle[]`. При отсутствии ключа API — адаптер пропускается (`pytest.skip` в интеграционных тестах).

**Принцип отбора:**  
Marketaux и Yahoo — основные ленты с ready-made сентиментом. RSS — быстрые макро-сигналы (ЦБ, регуляторы). NewsAPI и Alpha Vantage — при наличии ключей. Investing HTML-парсинг — не реализован (хрупко, low-ROI при наличии JSON API).

---

## 3. Импульс: реализованная схема

### Уровень 2 — `cheap_sentiment` (один скаляр на статью)

Приоритет: `raw_sentiment` с API → FinBERT (локально, кэш) → `price_pattern_boost` (floor).  
Подробно — `README.md § Уровень 2` и `pipeline/sentiment.py`.

### Уровень 3 — `DraftImpulse` (агрегат по окну)

```python
DraftImpulse(
    draft_bias_incremental,   # взвеш. среднее cheap_sentiment, канал INCREMENTAL
    regime_stress,            # взвеш. среднее |cheap_sentiment|, канал REGIME
    policy_stress,            # то же для POLICY_RATES
    articles_incremental, articles_regime, articles_policy,
    weight_sum_*, max_abs_*,
)
```

**Затухание:** `w = exp(−ln(2) / half_life * age_hours)`, `half_life=12ч` по умолчанию.  
**Каналы не смешиваются:** INCREMENTAL-средняя не содержит REGIME и наоборот.

Скалярный прокси для гейта: `pipeline/draft.py::single_scalar_draft_bias()`.

### Уровень 5 — LLM (Kerima-стиль)

`run_news_signal_pipeline(articles, cfg)` → `AggregatedNewsSignal(bias, confidence, summary, items)`.  
Вызывается только если гейт вернул `LITE` или `FULL`.  
Кэш ответа по `cache_key_llm(messages, model, prompt_version)`.

---

## 4. Гейт (уровень 4): принятое решение

Гибрид — реализован в `pipeline/gates.py`. Два профиля `ThresholdConfig` в `pipeline/types.py`:

| Профиль | T1 | N | Для |
|---------|----|---|-----|
| `PROFILE_GAME5M` | 0.12 | 8 | SNDK, NBIS, MU, LITE, CIEN, ASML |
| `PROFILE_CONTEXT` | 0.20 | 15 | MSFT, META, AMZN, NVDA |

Логика ветвей: `calendar_high_soon → regime → strong_bias → quiet → article_count`.  
Журнал калибровки (4 прогона) — `docs/calibration.md`.

---

## 5. Связь с календарём

`CalendarEvent HIGH` в окне `[now − after_min, now + before_min]` → гейт принудительно `FULL`.  
Окно задаётся: `NYSE_CALENDAR_HIGH_BEFORE_MIN` (30) / `NYSE_CALENDAR_HIGH_AFTER_MIN` (15).  
Реализовано: `pipeline/calendar_context.py::calendar_high_soon()`.

---

## 6. Что остаётся (план)

| Задача | Приоритет | Примечание |
|--------|-----------|-----------|
| **Уровень 6:** слияние `AggregatedNewsSignal` с техническим сигналом | высокий | Следующий этап |
| `regime_overhang` как явный член в формуле слияния | средний | Описан в §5.5 `news_calendar_inventory.md` |
| Telegram debug-бот `/news <TICKER>` | средний | `docs/testing_telegram_plan.md` |
| Более длинный окно `half_life` для REGIME (сутки vs 12ч) | низкий | Калибровка |
| `NEWS_WINDOW_HOURS` как env для обрезки по времени публикации | низкий | Сейчас `lookback_hours` в `Source` |
