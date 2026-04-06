# Архитектура пакета `sources`

Репозиторий **nyse** — слой **загрузки рыночных и контекстных данных** для US-инструментов (акции, ETF, индекс VIX, сырьё). Логика «сигналов», БД и бэктестов здесь **не** реализованы; планируется опора на общий стек **lse** (PostgreSQL, учёт издержек, лог-доходности) на следующих этапах.

## Структура каталогов

```
nyse/
├── README.md             # ← точка входа: обзор, схемы потоков, быстрый старт
├── domain.py             # enum Ticker, NewsArticle, NewsSignal, AggregatedNewsSignal, Trade
├── config_loader.py      # OPENAI_*, NYSE_* из config.env
├── config.env.example    # шаблон; config.env в .gitignore
├── pyproject.toml        # зависимости (pydantic, yfinance, requests…)
├── scripts/
│   ├── run_tests.sh      # pytest через conda env py11
│   └── calibrate_gate.py # офлайн-калибровка T1/T2/N на реальных данных
├── docs/
│   ├── architecture.md          ← этот файл
│   ├── dataflow.md              ← Mermaid-схемы полного потока (обновлено)
│   ├── calibration.md           ← журнал калибровки T1/T2/N (этап G)
│   ├── configuration.md         # секреты, ProxyAPI
│   ├── news_pipeline_hierarchy.md       # уровни 0–6, пороги
│   ├── news_sources_testing_and_pipeline_roadmap.md  # дорожная карта A–G
│   ├── testing_telegram_plan.md
│   ├── news_cache_and_impulse_proposals.md
│   └── news_calendar_inventory.md
├── pipeline/             # Новостной пайплайн (уровни 0–5, LLM, кэш)
│   ├── types.py          # DraftImpulse, ThresholdConfig, PROFILE_GAME5M, PROFILE_CONTEXT
│   ├── ingest.py         # ур. 0: слияние, дедуп
│   ├── channels.py       # ур. 1: NewsImpactChannel
│   ├── sentiment.py      # ур. 2: cheap_sentiment + price_pattern_boost
│   ├── draft.py          # ур. 3: DraftImpulse
│   ├── calendar_context.py  # этап C: calendar_high_soon
│   ├── gates.py          # ур. 4: decide_llm_mode
│   ├── news_cache.py     # этап E: FileCache для статей/draft
│   ├── llm_client.py     # этап F: HTTP LLM client
│   ├── llm_cache.py      # этап F: кэш LLM-ответов
│   ├── llm_digest.py     # этап F: lite-дайджест
│   ├── news_signal_schema.py    # ур. 5: Pydantic-схема LLM-ответа
│   ├── llm_batch_plan.py        # ур. 5: отбор батча
│   ├── news_signal_aggregator.py  # ур. 5: агрегация → AggregatedNewsSignal
│   ├── news_signal_prompt.py    # ур. 5: Kerima-стиль промпт
│   ├── news_signal_runner.py    # ур. 5: оркестратор
│   └── cache.py          # FileCache (базовый)
└── sources/
    ├── __init__.py       # публичный API: *Source + символы
    ├── symbols.py        # yfinance_symbol, finviz_symbol
    ├── candles.py        # OHLCV
    ├── metrics.py        # Finviz
    ├── earnings.py       # даты отчётности
    ├── ecalendar.py      # Investing.com JSON
    ├── news.py           # Yahoo (yfinance)
    ├── news_newsapi.py   # NewsAPI v2
    ├── news_marketaux.py # Marketaux v1
    ├── news_alphavantage.py  # Alpha Vantage NEWS_SENTIMENT
    ├── news_rss.py       # RSS/Atom
    └── news_shared.py    # общие утилиты
```

## Публичный API

Импорт из пакета `sources` (при установке пакета или при `PYTHONPATH` на корень репозитория):

| Экспорт | Назначение |
|---------|------------|
| `CandlesSource` | Свечи 1m / 1h / 1d, опционально pre/post market |
| `MetricsSource` | RSI, SMA%, ATR, beta, rel. volume и др. с Finviz |
| `EarningsSource` | Ближайшие прошлые/будущие earnings для `Ticker.is_stock()` |
| `CalendarSource` | События макро-календаря (фильтр по валютам) |
| `NewsSource` | Новости по тикеру (лимит и lookback в часах) |
| `yfinance_symbol` | Строка символа для Yahoo/yfinance |
| `finviz_symbol` | Строка символа для Finviz (override для VIX → VIXY) |
| `tickers_from_environ` | Список тикеров из `NYSE_TICKERS` или полный `Ticker` |

## Доменные модели (`domain.py`)

Файл в **корне репозитория**: типы не привязаны к конкретному источнику данных и могут использоваться сервисами вне `sources/`.

Импорт: `from domain import Ticker, Candle, ...`. При использовании только модулей `sources.*` корень репозитория подставляется в `sys.path` в `sources/__init__.py`; при прямом `import domain` задайте `PYTHONPATH` на корень репозитория или установите пакет в editable-режиме.

- **`Ticker`** — фиксированный universe; значение члена enum = канонический символ для **yfinance** (например `VIX = "^VIX"`, `BNO = "BNO"`).
- **`Candle`**, **`Period`** — свечи и интервал загрузки.
- **`TickerMetrics`**, **`Earnings`**, **`NewsArticle`**, **`CalendarEvent`** (+ **`Currency`**, важность события) — типизированный выход источников.

Метод **`Ticker.is_stock()`** отсекает ETF/индексы/сырьё для `EarningsSource`.

## Политика символов (`symbols.py`)

Один enum **`Ticker`**, разные внешние API требуют разных строк:

| Провайдер | Правило |
|-----------|---------|
| **yfinance** | `ticker.value` (свечи, earnings, news, цены) |
| **Finviz** | `ticker.value`, кроме **`VIX` → `VIXY`** (на скринере индекс `^VIX` обычно недоступен как equity-страница) |

Опционально список инструментов для сценариев без правки кода:

```bash
export NYSE_TICKERS=NVDA,MU,MSFT,^VIX
```

Значения — как у `Ticker.value` или имена enum (`SNDK`).

## Надёжность HTTP (`ecalendar.py`)

Запросы к API Investing.com выполняются с **повторными попытками** и паузами при **429** и сетевых ошибках (аналогично идее backoff в **lse** для HTML-календаря). Таймаут чтения увеличен относительно «голого» одноразового GET.

## Зависимости (ожидаемые)

- **yfinance**, **pandas** — свечи, earnings, news  
- **finvizfinance** — metrics  
- **requests** — календарь  
- **pytz** — earnings (UTC)

Файл зависимостей репозитория (`requirements.txt` / `pyproject.toml`) может быть добавлен отдельно под ваш менеджер окружений.

## Связь с **lse**

| Аспект | **nyse** (`sources`) | **lse** |
|--------|----------------------|---------|
| Новости | в основном Yahoo (`get_news`) | KB: RSS, NewsAPI, Investing-лента, sentiment |
| Календарь | JSON `endpoints.investing.com` | HTML Investing + опционально Alpha Vantage |
| Хранение | нет (только fetch) | PostgreSQL, `knowledge_base`, котировки |

План эволюции: общие абстракции провайдеров, дедуп по `link`/id, опциональный слой записи в БД по образцу **lse**.

## Визуализация потоков данных

Схемы **до/после** рефакторинга источников и обзор текущего контура — в **[dataflow.md](./dataflow.md)** (диаграммы Mermaid; на GitHub отображаются в превью файла).
