# Архитектура пакета `sources`

Репозиторий **nyse** — слой **загрузки рыночных и контекстных данных** для US-инструментов (акции, ETF, индекс VIX, сырьё). Логика «сигналов», БД и бэктестов здесь **не** реализованы; планируется опора на общий стек **lse** (PostgreSQL, учёт издержек, лог-доходности) на следующих этапах.

## Структура каталогов

```
nyse/
├── domain.py             # enum Ticker, датаклассы домена (общая модель)
├── scripts/
│   └── run_tests.sh    # pytest через conda env py11
├── docs/
│   ├── architecture.md   ← этот файл
│   ├── dataflow.md       ← схемы «было → стало» (Mermaid)
│   ├── news_calendar_inventory.md  ← инвентаризация новостей/календаря, Marketaux, типизация
│   ├── testing_telegram_plan.md    ← план тестов (новости — фокус), stub техники, Telegram
│   ├── news_cache_and_impulse_proposals.md  ← кэш без БД, свежесть, макро, методы импульса
│   └── news_pipeline_hierarchy.md   ← §5.4 + FinBERT + Kerima LLM + пороги и кэш
├── pipeline/           # каналы §5.4, черновой импульс, гейты LLM, FileCache (без LLM)
└── sources/
    ├── __init__.py       # публичный API: *Source + символы; добавляет корень в sys.path
    ├── symbols.py        # yfinance_symbol, finviz_symbol, tickers_from_environ
    ├── candles.py        # OHLCV через yfinance
    ├── metrics.py        # скринер Finviz (finvizfinance)
    ├── earnings.py       # даты отчётности через yfinance
    ├── ecalendar.py      # макро-календарь (JSON Investing.com)
    └── news.py           # лента Yahoo через yfinance
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
