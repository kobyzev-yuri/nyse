# nyse — News Pipeline & Data Layer

Пакет **nyse** — слой сбора рыночных данных и обработки новостей для US-инструментов.  
Работает совместно с **pystockinvest** (сигналы, агент, TradeBuilder) и **lse** (PostgreSQL, GAME_5M, исполнение).

---

## Быстрый старт

```bash
# установка в editable-режиме (conda env py11)
conda activate py11
pip install -e ".[sentiment]"

# конфиг
cp config.env.example config.env   # заполни OPENAI_*, ключи API

# тесты
python -m pytest tests/unit/ -q                          # 140 unit-тестов, без сети
python -m pytest tests/ -v -m integration                # интеграционные (нужна сеть)

# калибровка гейта
python scripts/calibrate_gate.py --profile game5m --tickers SNDK NBIS CIEN --days 1
python scripts/calibrate_gate.py --profile context --tickers MSFT META NVDA --days 3
```

---

## Архитектура системы

```
┌───────────────────────────────────────────────────────────────────┐
│                         lse (исполнение)                          │
│  PostgreSQL · GAME_5M · positions · CatBoost · Telegram bot       │
└────────────────────────────┬──────────────────────────────────────┘
                             │ Trade (entry_type, position, summaries)
┌────────────────────────────▼──────────────────────────────────────┐
│                    pystockinvest / Orchestrator                    │
│                                                                    │
│   TechnicalAgent ──┐                                               │
│   NewsAgent     ───┼──► TradeBuilder ──► domain.Trade             │
│   CalendarAgent ──┘                                                │
└──────┬──────────────────────┬────────────────────────┬────────────┘
       │ TechnicalSignal      │ AggregatedNewsSignal   │ CalendarSignal
       │                      │                        │
  [техника]           ┌───────▼──────────┐        [calendar]
  CatBoost /          │  nyse pipeline   │        sources/ecalendar
  TA-модели           │  (этот пакет)    │
                      └──────────────────┘
```

---

## Полный поток данных: от источника к сделке

```
                         ┌─────────────────────────────────┐
                         │      ВНЕШНИЕ ИСТОЧНИКИ          │
                         │                                 │
  Yahoo (yfinance) ──────►  NewsArticle[]                  │
  Marketaux ─────────────►  NewsArticle[] + raw_sentiment  │
  NewsAPI ────────────────►  NewsArticle[]                  │
  RSS / Alpha Vantage ───►  NewsArticle[]                  │
                         └──────────┬──────────────────────┘
                                    │
                         ╔══════════▼══════════╗
                         ║   УРОВЕНЬ 0         ║
                         ║  Слияние и дедуп    ║
                         ║  pipeline/ingest    ║
                         ╚══════════╤══════════╝
                                    │ NewsArticle[] (уникальные, в окне)
                         ╔══════════▼══════════╗
                         ║   УРОВЕНЬ 1         ║
                         ║  NewsImpactChannel  ║  ← словари: war/sanctions/Fed/FOMC
                         ║  pipeline/channels  ║
                         ╚══════════╤══════════╝
                                    │ channel: INCREMENTAL | REGIME | POLICY_RATES
                         ╔══════════▼══════════╗
                         ║   УРОВЕНЬ 2         ║
                         ║  cheap_sentiment    ║  ← raw_sentiment API (приоритет)
                         ║  pipeline/sentiment ║  ← FinBERT (локально)
                         ║                     ║  ← price_pattern_boost (floor)
                         ╚══════════╤══════════╝
                                    │ cheap_sentiment ∈ [−1, 1]
                         ╔══════════▼══════════╗
                         ║   УРОВЕНЬ 3         ║
                         ║  DraftImpulse       ║  ← экспоненциальное затухание (T½=12ч)
                         ║  pipeline/draft     ║  ← отдельно по каналам (не мешать)
                         ╚══════════╤══════════╝
                                    │ draft_bias, regime_stress, policy_stress
                         ╔══════════▼══════════╗
                         ║   УРОВЕНЬ 4 (ГЕЙТ)  ║
                         ║  decide_llm_mode    ║  ← ThresholdConfig: T1, T2, N
                         ║  pipeline/gates     ║  ← CalendarEvent HIGH → FULL
                         ╚══════════╤══════════╝
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
           SKIP                   LITE                  FULL
           (draft_bias             │                     │
           возвращается)    ╔══════▼════════╗   ╔══════▼════════╗
                            ║  lite-дайджест ║   ║  Уровень 5    ║
                            ║  llm_digest   ║   ║  LLM (Kerima) ║
                            ╚══════╤════════╝   ╚══════╤════════╝
                                   │                   │
                                   └─────────┬─────────┘
                                             │
                                  ╔══════════▼══════════╗
                                  ║  AggregatedNewsSignal║
                                  ║  bias, confidence   ║
                                  ╚══════════╤══════════╝
                                             │
                               ┌─────────────▼─────────────┐
                               │      TradeBuilder          │
                               │  (pystockinvest)           │
                               │                            │
                               │  final_bias =              │
                               │    0.55 × tech_bias        │
                               │  + 0.30 × news_bias        │
                               │  + 0.15 × calendar_bias    │
                               └─────────────┬─────────────┘
                                             │
                                      domain.Trade
```

---

## Технический сигнал Kerima (`TechnicalSignal`)

Вычисляется в **pystockinvest** независимо от новостей.

```
TechnicalSignal
├── bias                        ∈ [−1, +1]   итоговое направление
├── trend_score                 ∈ [0, 1]     сила тренда (MA, EMA)
├── momentum_score              ∈ [0, 1]     импульс (RSI, ROC)
├── mean_reversion_score        ∈ [0, 1]     откат к среднему (Bollinger)
├── breakout_score              ∈ [0, 1]     пробой уровня
├── volatility_regime           ∈ [0, 1]     режим волатильности (ATR/VIX)
├── relative_strength_score     ∈ [0, 1]     относительная сила vs сектор/SPY
├── market_alignment_score      ∈ [0, 1]     согласованность с рынком (SMH, QQQ)
├── exhaustion_score            ∈ [0, 1]     истощение движения
├── support_resistance_pressure ∈ [0, 1]     давление уровней S/R
├── tradeability_score          ∈ [0, 1]     торгуемость (< 0.40 → не входить)
├── confidence                  ∈ [0, 1]     уверенность сигнала
├── target_snapshot             TechnicalSnapshot (TickerData + TickerMetrics)
└── summary                     list[str]    текстовые комментарии
```

**TradeBuilder** — веса финальной уверенности:

```
confidence = 0.50 × tech_conf
           + 0.30 × news_conf
           + 0.20 × cal_conf
           + min(|final_bias|, 1.0) × 0.15   ← agreement bonus
           × (1 − 0.35 × upcoming_event_risk) ← calendar penalty
```

---

## Новостной пайплайн: уровни

| Уровень | Модуль | Входные данные | Выход | LLM |
|---------|--------|---------------|-------|-----|
| 0 | `pipeline/ingest.py` | raw `NewsArticle[]` | дедупл. `NewsArticle[]` | нет |
| 1 | `pipeline/channels.py` | заголовок + summary | `NewsImpactChannel` | нет |
| 2 | `pipeline/sentiment.py` | текст статьи | `cheap_sentiment` ∈ [−1,1] | нет |
| 3 | `pipeline/draft.py` | scored articles | `DraftImpulse` | нет |
| 4 | `pipeline/gates.py` | `DraftImpulse` + `GateContext` | `LLMMode` | нет |
| 5 | `pipeline/news_signal_runner.py` | отобранные статьи | `AggregatedNewsSignal` | **да** |

### Уровень 2 — `cheap_sentiment`: логика приоритета

```
raw_sentiment (с API)   ← первый приоритет
        ↓ нет
FinBERT (локально)      ← transformers, кэш по hash(text)
        ↓
price_pattern_boost     ← floor: "Jumped 15%" → +0.8 даже при нейтральном FinBERT
```

**Масштаб `price_pattern_boost`:**

| Движение | Сигнал |
|----------|--------|
| ≥ 20% | ±1.0 |
| ≥ 10% | ±0.8 |
| ≥ 5%  | ±0.6 |
| ≥ 2%  | ±0.4 |
| < 2%  | ±0.2 |

### Уровень 4 — Гейт: порядок приоритетов

```
1. calendar_high_soon         → FULL  (HIGH событие в ближайшие N минут)
2. regime + confidence ≥ T2   → FULL  (REGIME c уверенностью выше T2)
3. |bias| ≥ T1 × 2            → FULL  (сильный сигнал — приоритет над кол-вом статей)
4. |bias| < T1, no REGIME     → SKIP  (спокойный фон)
5. article_count > N          → LITE  (много статей — lite-дайджест)
6. иначе                      → LITE
```

---

## Профили ThresholdConfig

| Профиль | T1 | T1×2 (FULL) | N | Для |
|---------|-----|------------|---|-----|
| `PROFILE_GAME5M` | **0.12** | 0.24 | **8** | SNDK, NBIS, MU, LITE, CIEN, ASML |
| `PROFILE_CONTEXT` | **0.20** | 0.40 | **15** | MSFT, META, AMZN, NVDA (фон) |

```python
from pipeline import PROFILE_GAME5M, PROFILE_CONTEXT, decide_llm_mode
mode = decide_llm_mode(PROFILE_GAME5M, gate_context)
```

Обоснование: у GAME_5M тикеров **3–9 статей/день** (vs 40–50 у крупных). При малом числе статей каждая весит больше, нижний T1 критичен.

---

## Структура пакета

```
nyse/
├── README.md
├── domain.py                   # Ticker, NewsArticle, NewsSignal, AggregatedNewsSignal, Trade…
├── config_loader.py            # OPENAI_*, NYSE_*, из config.env
├── config.env.example
├── pyproject.toml
│
├── pipeline/                   # Новостной пайплайн (уровни 0–5)
│   ├── types.py                # DraftImpulse, GateContext, LLMMode, ThresholdConfig, PROFILE_*
│   ├── ingest.py               # Ур. 0: слияние, дедуп
│   ├── channels.py             # Ур. 1: NewsImpactChannel
│   ├── sentiment.py            # Ур. 2: cheap_sentiment + price_pattern_boost
│   ├── draft.py                # Ур. 3: DraftImpulse (экспоненциальное затухание)
│   ├── calendar_context.py     # этап C: calendar_high_soon → GateContext
│   ├── gates.py                # Ур. 4: decide_llm_mode
│   ├── news_cache.py           # этап E: FileCache для статей и draft
│   ├── llm_client.py           # этап F: OpenAI-compatible HTTP client
│   ├── llm_cache.py            # этап F: кэш LLM-ответов
│   ├── llm_digest.py           # этап F: lite-дайджест промпт
│   ├── news_signal_schema.py   # Ур. 5: Pydantic-схема ответа LLM
│   ├── llm_batch_plan.py       # Ур. 5: отбор статей для батча
│   ├── news_signal_aggregator.py # Ур. 5: NewsSignal[] → AggregatedNewsSignal
│   ├── news_signal_prompt.py   # Ур. 5: structured LLM prompt (Kerima-стиль)
│   ├── news_signal_runner.py   # Ур. 5: оркестратор run_news_signal_pipeline
│   └── cache.py                # FileCache (базовый)
│
├── sources/                    # Источники рыночных данных
│   ├── news.py                 # Yahoo (yfinance)
│   ├── news_newsapi.py         # NewsAPI v2
│   ├── news_marketaux.py       # Marketaux v1
│   ├── news_alphavantage.py    # Alpha Vantage NEWS_SENTIMENT
│   ├── news_rss.py             # RSS/Atom
│   ├── candles.py              # OHLCV (yfinance)
│   ├── metrics.py              # Finviz (RSI, ATR, …)
│   ├── earnings.py             # Даты отчётности
│   └── ecalendar.py            # Macro-calendar (Investing.com JSON)
│
├── scripts/
│   └── calibrate_gate.py       # Калибровка T1/T2/N на реальных данных
│
├── tests/
│   ├── unit/                   # 140 тестов, без сети
│   └── integration/            # smoke-тесты (pytest.skip без сети)
│
└── docs/
    ├── architecture.md         # Структура пакета sources
    ├── dataflow.md             # Mermaid-схемы потоков данных
    ├── calibration.md          # Журнал калибровки T1/T2/N (4 прогона)
    ├── news_pipeline_hierarchy.md  # Уровни 0–6, пороги
    ├── news_sources_testing_and_pipeline_roadmap.md  # Дорожная карта A–G
    ├── configuration.md
    ├── testing_telegram_plan.md
    ├── news_cache_and_impulse_proposals.md
    └── news_calendar_inventory.md
```

---

## Конфигурация

Ключевые переменные в `config.env`:

| Переменная | Назначение | Дефолт |
|------------|-----------|--------|
| `OPENAI_BASE_URL` | Эндпоинт LLM API | — |
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
# профиль GAME_5M (интрадей тикеры)
python scripts/calibrate_gate.py --profile game5m \
    --tickers SNDK NBIS MU LITE CIEN ASML --days 1

# профиль CONTEXT (крупные тикеры, фон)
python scripts/calibrate_gate.py --profile context \
    --tickers MSFT META AMZN NVDA --days 3

# ручные пороги
python scripts/calibrate_gate.py --t1 0.15 --max-n 10 --tickers SNDK MU --days 7
```

Журнал прогонов и выводы — `docs/calibration.md`.

---

## Интеграция с pystockinvest / lse

```python
from pipeline import PROFILE_GAME5M, run_news_signal_pipeline, decide_llm_mode
from pipeline import enrich_cheap_sentiment, draft_impulse, scored_from_news_articles
from pipeline import build_gate_context

# 1. Обогатить статьи сентиментом
articles = enrich_cheap_sentiment(raw_articles)

# 2. Черновой импульс → гейт
scored = scored_from_news_articles(articles)
d = draft_impulse(scored)
ctx = build_gate_context(
    draft_bias=d.draft_bias_incremental,
    regime_present=d.regime_stress > PROFILE_GAME5M.regime_stress_min,
    regime_rule_confidence=0.85 if d.regime_stress > 0.05 else 0.0,
    calendar_events=calendar_events,
    article_count=len(articles),
)

# 3. Уровень 5 (если нужен LLM)
from pipeline.types import LLMMode
if decide_llm_mode(PROFILE_GAME5M, ctx) != LLMMode.SKIP:
    signal = run_news_signal_pipeline(articles, cfg=PROFILE_GAME5M)
    # signal: AggregatedNewsSignal(bias, confidence, summary, items)
```

---

## Дорожная карта

| Этап | Статус | Содержание |
|------|--------|-----------|
| A–G | ✅ закрыто | Источники, pipeline 0–5, LLM-гейт, калибровка |
| **Уровень 6** | 🔜 следующий | Подключить `AggregatedNewsSignal` к агенту GAME_5M |
| G+ | ♻ ongoing | Калибровка на неделях с реальными движениями цены |

Детали — `docs/news_sources_testing_and_pipeline_roadmap.md`.
