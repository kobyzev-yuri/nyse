# nyse — News Pipeline & Market Data

Автономный пакет для сбора рыночных данных и обработки финансовых новостей.  
**Хранилище:** `FileCache` (JSON-файлы в `.cache/nyse`). PostgreSQL не требуется.

---

## Быстрый старт

```bash
conda activate py11
pip install -e ".[sentiment]"          # +transformers для FinBERT

cp config.env.example config.env       # заполни OPENAI_*, ключи API

python -m pytest tests/unit/ -q        # 140 тестов, без сети
python -m pytest tests/ -m integration # smoke-тесты (нужна сеть)

# калибровка гейта на реальных данных
python scripts/calibrate_gate.py --profile game5m --tickers SNDK NBIS CIEN --days 1
python scripts/calibrate_gate.py --profile context --tickers MSFT META NVDA --days 3
```

---

## Поток данных

```
  Yahoo (yfinance) ──────┐
  Marketaux ─────────────┤  raw NewsArticle[]
  NewsAPI / RSS ──────────┤  (+ raw_sentiment с API)
  Alpha Vantage ─────────┘
          │
  ╔═══════▼════════╗
  ║  Уровень 0     ║  pipeline/ingest.py
  ║  Слияние,      ║  дедуп по URL, окно времени
  ║  дедупликация  ║
  ╚═══════╤════════╝
          │ NewsArticle[] (уникальные)
  ╔═══════▼════════╗
  ║  Уровень 1     ║  pipeline/channels.py
  ║  Канал         ║  словари: war/sanctions → REGIME
  ║  воздействия   ║  Fed/FOMC → POLICY_RATES
  ╚═══════╤════════╝  иначе → INCREMENTAL
          │ NewsImpactChannel
  ╔═══════▼════════╗
  ║  Уровень 2     ║  pipeline/sentiment.py
  ║  cheap_        ║  1. raw_sentiment от API
  ║  sentiment     ║  2. FinBERT (TTL-кэш)
  ╚═══════╤════════╝  3. price_pattern_boost (floor)
          │ float ∈ [−1, 1]
  ╔═══════▼════════╗
  ║  Уровень 3     ║  pipeline/draft.py
  ║  DraftImpulse  ║  экспоненциальное затухание T½=12ч
  ╚═══════╤════════╝  INCREMENTAL / REGIME / POLICY отдельно
          │ draft_bias, regime_stress, policy_stress
  ╔═══════▼════════╗
  ║  Уровень 4     ║  pipeline/gates.py
  ║  ГЕЙТ          ║  ThresholdConfig: T1, T2, N
  ╚═══╤══╤══╤═════╝  + CalendarEvent HIGH
      │  │  │
    SKIP LITE FULL
      │   │    │
      │  llm_digest  ──────────────────┐
      │  (lite-промпт)                 │
      │                         news_signal_runner.py
      │                         LLM → Pydantic → агрегация
      │                                │
      └────────────────┬───────────────┘
                       │
          ╔════════════▼═══════════╗
          ║  AggregatedNewsSignal  ║  ← ВЫХОД пакета
          ║  bias      ∈ [−1, +1] ║
          ║  confidence ∈ [0,  1] ║
          ║  summary   list[str]  ║
          ║  items     NewsSignal[]║
          ╚════════════════════════╝
```

---

## Уровни пайплайна

| Ур. | Модуль | Вход | Выход | LLM |
|-----|--------|------|-------|-----|
| 0 | `pipeline/ingest.py` | `NewsArticle[]` (несколько источников) | дедупл. `NewsArticle[]` | — |
| 1 | `pipeline/channels.py` | заголовок + summary | `NewsImpactChannel` | — |
| 2 | `pipeline/sentiment.py` | текст статьи | `cheap_sentiment` | — |
| 3 | `pipeline/draft.py` | оценённые статьи | `DraftImpulse` | — |
| 4 | `pipeline/gates.py` | `DraftImpulse` + `GateContext` | `LLMMode` | — |
| 5 | `pipeline/news_signal_runner.py` | отобранные статьи | `AggregatedNewsSignal` | **да** |

### Уровень 2 — логика `cheap_sentiment`

```
1. raw_sentiment (от API, Marketaux и др.)  ← приоритет, clip(−1, 1)
         ↓ нет
2. FinBERT (ProsusAI/finbert, локально)    ← TTL-кэш по hash(text)
         ↓
3. price_pattern_boost                     ← floor поверх FinBERT:
   "Jumped 15%" → +0.8  (FinBERT дал 0.0 из-за вопроса в конце — берём буст)
   "Sinks 7%"  → −0.6
```

| Движение | boost |
|----------|-------|
| ≥ 20% | ±1.0 |
| ≥ 10% | ±0.8 |
| ≥  5% | ±0.6 |
| ≥  2% | ±0.4 |
| < 2%  | ±0.2 |

### Уровень 4 — порядок ветвей гейта

```
1. calendar_high_soon          → FULL  (HIGH-событие скоро)
2. regime_present AND ≥ T2     → FULL  (геополитика / санкции)
3. |bias| ≥ T1 × 2             → FULL  (сильный сигнал, приоритет над счётчиком)
4. |bias| < T1, no REGIME      → SKIP  (спокойный фон, LLM не нужен)
5. article_count > N           → LITE  (много статей — lite-дайджест)
6. иначе                       → LITE
```

---

## Профили ThresholdConfig

Два готовых профиля, откалиброванных на реальных данных Yahoo (2026-04-06):

| Профиль | T1 | T1×2 (→FULL) | N | Для тикеров |
|---------|----|-------------|---|-------------|
| `PROFILE_GAME5M` | **0.12** | 0.24 | **8** | SNDK, NBIS, MU, LITE, CIEN, ASML |
| `PROFILE_CONTEXT` | **0.20** | 0.40 | **15** | MSFT, META, AMZN, NVDA |

У GAME_5M тикеров **3–9 статей/день** (у крупных 40–50) — каждая статья весит больше, поэтому T1 ниже.

```python
from pipeline import PROFILE_GAME5M, decide_llm_mode, build_gate_context

ctx = build_gate_context(
    draft_bias=d.draft_bias_incremental,
    regime_present=d.regime_stress > PROFILE_GAME5M.regime_stress_min,
    regime_rule_confidence=0.85 if d.regime_stress > 0.05 else 0.0,
    calendar_events=calendar_events,
    article_count=len(articles),
)
mode = decide_llm_mode(PROFILE_GAME5M, ctx)  # LLMMode.SKIP | LITE | FULL
```

---

## Использование

```python
from pipeline import (
    enrich_cheap_sentiment,
    scored_from_news_articles,
    draft_impulse,
    build_gate_context,
    decide_llm_mode,
    run_news_signal_pipeline,
    PROFILE_GAME5M,
    LLMMode,
)

# 1. Получить статьи через sources/
from sources.news import Source
from domain import Ticker
articles = Source(max_per_ticker=50, lookback_hours=24).get_articles([Ticker.SNDK])

# 2. Уровни 2–3: сентимент и черновой импульс
articles = enrich_cheap_sentiment(articles)
scored   = scored_from_news_articles(articles)
impulse  = draft_impulse(scored)

# 3. Уровень 4: гейт
ctx  = build_gate_context(
    draft_bias=impulse.draft_bias_incremental,
    regime_present=impulse.regime_stress > PROFILE_GAME5M.regime_stress_min,
    regime_rule_confidence=0.85 if impulse.regime_stress > 0.05 else 0.0,
    calendar_events=[],          # CalendarEvent[] из sources/ecalendar при необходимости
    article_count=len(articles),
)
mode = decide_llm_mode(PROFILE_GAME5M, ctx)

# 4. Уровень 5: LLM (только если нужен)
if mode != LLMMode.SKIP:
    signal = run_news_signal_pipeline(articles, cfg=PROFILE_GAME5M)
    print(f"bias={signal.bias:.3f}  confidence={signal.confidence:.3f}")
    # AggregatedNewsSignal(bias, confidence, summary, items)
```

---

## Структура пакета

```
nyse/
├── README.md
├── domain.py            # Ticker, NewsArticle, NewsSignal, AggregatedNewsSignal…
├── config_loader.py     # OPENAI_*, NYSE_* из config.env
├── config.env.example
├── pyproject.toml
│
├── pipeline/
│   ├── cache.py                  # FileCache: JSON-файлы, TTL, без БД
│   ├── types.py                  # DraftImpulse, ThresholdConfig, PROFILE_GAME5M/CONTEXT
│   ├── ingest.py                 # Ур. 0: слияние + дедуп
│   ├── channels.py               # Ур. 1: NewsImpactChannel
│   ├── sentiment.py              # Ур. 2: cheap_sentiment + price_pattern_boost
│   ├── draft.py                  # Ур. 3: DraftImpulse
│   ├── calendar_context.py       # CalendarEvent HIGH → GateContext
│   ├── gates.py                  # Ур. 4: decide_llm_mode
│   ├── news_cache.py             # FileCache для статей и draft_impulse
│   ├── llm_client.py             # OpenAI-compatible HTTP client
│   ├── llm_cache.py              # кэш LLM-ответов (FileCache)
│   ├── llm_digest.py             # lite-дайджест промпт
│   ├── news_signal_schema.py     # Pydantic-схема JSON-ответа LLM
│   ├── llm_batch_plan.py         # отбор статей для батча
│   ├── news_signal_aggregator.py # NewsSignal[] → AggregatedNewsSignal
│   ├── news_signal_prompt.py     # structured LLM prompt
│   └── news_signal_runner.py     # Ур. 5: оркестратор
│
├── sources/
│   ├── news.py              # Yahoo (yfinance)
│   ├── news_newsapi.py      # NewsAPI v2
│   ├── news_marketaux.py    # Marketaux v1
│   ├── news_alphavantage.py # Alpha Vantage NEWS_SENTIMENT
│   ├── news_rss.py          # RSS/Atom
│   ├── candles.py           # OHLCV (yfinance)
│   ├── metrics.py           # Finviz (RSI, ATR…)
│   ├── earnings.py          # Даты отчётности
│   └── ecalendar.py         # Macro-calendar (Investing.com JSON)
│
├── scripts/
│   └── calibrate_gate.py    # офлайн-калибровка T1/T2/N
│
├── tests/
│   ├── unit/                # 140 тестов, без сети
│   └── integration/         # smoke (pytest.skip без сети / ключей)
│
└── docs/
    ├── calibration.md                        # журнал 4 прогонов T1/T2/N
    ├── news_pipeline_hierarchy.md            # уровни 0–6, пороги
    ├── dataflow.md                           # Mermaid-схемы
    ├── architecture.md                       # структура sources/
    ├── news_sources_testing_and_pipeline_roadmap.md
    ├── configuration.md
    ├── testing_telegram_plan.md
    ├── news_cache_and_impulse_proposals.md
    └── news_calendar_inventory.md
```

---

## FileCache — хранилище без БД

Весь кэш пакета — обычные JSON-файлы на диске. Ни PostgreSQL, ни Redis не нужны.

### Устройство

```
.cache/nyse/                       ← NYSE_CACHE_ROOT (по умолчанию)
├── 3f8a1c…d4.json                 ← один файл = один ключ
├── 9b2e7f…a1.json
└── …

Каждый файл:
{
    "value":       <любой JSON-сериализуемый объект>,
    "_expires_at": 1712345678.0    ← unix timestamp; при чтении: просрочен → удалить
}
```

Имя файла = `sha256(ключ).json`. TTL проверяется лениво при первом чтении.

### Три независимых слоя

```
┌─────────────────────────────────────────────────────────────────┐
│  FileCache   (pipeline/cache.py)                                │
│  root=NYSE_CACHE_ROOT   ключ → sha256 → .json с TTL            │
└──────────────┬──────────────────┬──────────────────┬───────────┘
               │                  │                  │
  ┌────────────▼────────┐ ┌───────▼──────────┐ ┌────▼──────────────┐
  │  Новости + Draft    │ │  Сентимент       │ │  LLM-ответы       │
  │  news_cache.py      │ │  sentiment.py    │ │  llm_cache.py     │
  │                     │ │                  │ │                   │
  │  Ключ:              │ │  Ключ:           │ │  Ключ:            │
  │  raw|v1|            │ │  cheap_sentiment │ │  llm|v1|          │
  │    provider|        │ │    |sha256(       │ │    prompt_ver|    │
  │    ticker|extra     │ │    model+text)   │ │    model|         │
  │  draft|v1|          │ │                  │ │    sha256(msgs)   │
  │    ticker|w…|h…     │ │  Значение:       │ │                   │
  │                     │ │  float [−1, 1]   │ │  Значение:        │
  │  Значение:          │ │                  │ │  str (raw JSON    │
  │  NewsArticle[] JSON │ │  TTL: env        │ │  из LLM)          │
  │  DraftImpulse dict  │ │  NYSE_SENTIMENT_ │ │                   │
  │                     │ │  CACHE_TTL_SEC   │ │  TTL: env         │
  │  TTL: env           │ │  (def: 86400)    │ │  NYSE_LLM_CACHE_  │
  │  NYSE_NEWS_RAW_     │ │                  │ │  TTL_SEC          │
  │  TTL_SEC (def: 900) │ └──────────────────┘ │  (def: 3600)      │
  └─────────────────────┘                      └───────────────────┘
```

### Жизненный цикл ключа

```
get(key)
  ├── файл не найден          → None  (промах)
  ├── _expires_at < now()     → unlink() + None  (истёк, удалён)
  └── ОК                      → value  (попадание)

set(key, value, ttl_sec)
  └── записать {value, _expires_at=now()+ttl}  → sha256(key).json
```

### Готовые фабрики

```python
from pipeline.news_cache import default_news_file_cache   # TTL=NYSE_NEWS_RAW_TTL_SEC
from pipeline.llm_cache  import default_llm_file_cache    # TTL=NYSE_LLM_CACHE_TTL_SEC
from pipeline.sentiment  import enrich_with_default_cache # создаёт кэш внутри

# или напрямую
from pipeline import FileCache
cache = FileCache(root=Path(".cache/myapp"), default_ttl_sec=3600)
cache.set("my_key", {"data": 42})
val = cache.get("my_key")  # {"data": 42}  или None если истёк
```

### TTL по умолчанию

| Слой | env-переменная | Дефолт |
|------|---------------|--------|
| Сырые новости (`raw|…`) | `NYSE_NEWS_RAW_TTL_SEC` | 900 с (15 мин) |
| Сентимент (`cheap_sentiment|…`) | `NYSE_SENTIMENT_CACHE_TTL_SEC` | 86400 с (24 ч) |
| LLM-ответы (`llm|…`) | `NYSE_LLM_CACHE_TTL_SEC` | 3600 с (1 ч) |
| DraftImpulse (`draft|…`) | `NYSE_NEWS_AGGREGATE_TTL_SEC` | 300 с (5 мин) |

---

## Конфигурация

| Переменная | Назначение | Дефолт |
|------------|-----------|--------|
| `OPENAI_BASE_URL` | Эндпоинт LLM | — |
| `OPENAI_API_KEY` | API-ключ | — |
| `OPENAI_MODEL` | Модель | `gpt-4o` |
| `NYSE_SENTIMENT_LOCAL` | Включить FinBERT | `true` |
| `NYSE_SENTIMENT_CACHE_TTL_SEC` | TTL кэша сентимента | `86400` |
| `NYSE_LLM_CACHE_TTL_SEC` | TTL кэша LLM-ответов | `3600` |
| `NYSE_CACHE_ROOT` | Корень FileCache | `.cache/nyse` |
| `NYSE_CALENDAR_HIGH_BEFORE_MIN` | Окно HIGH-события вперёд | `30` |
| `NYSE_CALENDAR_HIGH_AFTER_MIN` | Окно HIGH-события назад | `15` |

Полный список — `docs/configuration.md`.

---

## Калибровка гейта

```bash
python scripts/calibrate_gate.py --profile game5m \
    --tickers SNDK NBIS MU LITE CIEN ASML --days 1

python scripts/calibrate_gate.py --profile context \
    --tickers MSFT META AMZN NVDA --days 3

python scripts/calibrate_gate.py --t1 0.15 --max-n 10 --tickers SNDK MU --days 7
```

Журнал прогонов и выводы — `docs/calibration.md`.

---

## Дорожная карта

| Этап | Статус | Содержание |
|------|--------|-----------|
| A–G | ✅ | Источники, pipeline уровни 0–5, LLM-гейт, калибровка |
| Уровень 6 | 🔜 | Слияние `AggregatedNewsSignal` с техническим сигналом |
| G+ | ♻ | Калибровка на реальных ценовых движениях |

Детали — `docs/news_sources_testing_and_pipeline_roadmap.md`.
