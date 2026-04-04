# Потоки данных: было и стало

Документ для **визуального** сопоставления архитектуры источников до рефакторинга и после. Диаграммы в формате **Mermaid** корректно отображаются на **GitHub** при просмотре `.md` файла в репозитории.

---

## 1. Было (исходная версия `sources`)

Каждый модуль содержал **свою копию** `parse_ticker()` с длинной цепочкой `if/elif`. Разные API получали **несогласованные** строки для одного логического инструмента (типичный пример: **VIX** — `^VIX` в одних местах и **VIXY** в других без явной политики). Ошибка в имени публичного API: `get_dayly_candles`. Календарь — один запрос без повторов при 429.

```mermaid
flowchart TB
    subgraph consumers["Потребители (ваш код)"]
        APP["Скрипты / сервисы"]
    end

    subgraph dup["Дублирование parse_ticker"]
        P1["candles.parse_ticker"]
        P2["earnings.parse_ticker"]
        P3["metrics.parse_ticker"]
        P4["news.parse_ticker"]
    end

    APP --> Candles["CandlesSource"]
    APP --> Metrics["MetricsSource"]
    APP --> Earn["EarningsSource"]
    APP --> News["NewsSource"]
    APP --> Cal["CalendarSource"]

    Candles --> P1 --> YF1["yfinance"]
    Earn --> P2 --> YF2["yfinance"]
    Metrics --> P3 --> FV["finvizfinance"]
    News --> P4 --> YF3["yfinance"]

    Cal --> REQ1["requests → Investing JSON\n(без retry)"]

    style P1 fill:#f96,stroke:#333
    style P2 fill:#f96,stroke:#333
    style P3 fill:#f96,stroke:#333
    style P4 fill:#f96,stroke:#333
```

**Проблемы:** четыре места правки при добавлении тикера; риск рассинхрона **VIX** / **BNO**; хрупкий календарь при rate limit.

---

## 2. Стало (текущая версия)

Единая точка сопоставления **`symbols.py`**: **`yfinance_symbol()`** и **`finviz_symbol()`**. Модули источников импортируют только их. **`Ticker.value`** — канон для Yahoo; для Finviz явный override **VIX → VIXY**. Дневные свечи: **`get_daily_candles`** (+ устаревший алиас с предупреждением). Календарь: **`_get_json_with_retries`**. Опционально **`NYSE_TICKERS`** для списка инструментов без изменения enum.

```mermaid
flowchart TB
    subgraph consumers["Потребители (ваш код)"]
        APP["Скрипты / сервисы"]
    end

    subgraph sym["Единый слой symbols.py"]
        YFS["yfinance_symbol(ticker)"]
        FVS["finviz_symbol(ticker)"]
        ENV["tickers_from_environ()"]
    end

    APP --> ENV
    APP --> Candles["CandlesSource"]
    APP --> Metrics["MetricsSource"]
    APP --> Earn["EarningsSource"]
    APP --> News["NewsSource"]
    APP --> Cal["CalendarSource"]

    Candles --> YFS
    Earn --> YFS
    News --> YFS
    Metrics --> FVS

    YFS --> YF["yfinance\n(свечи, earnings, news)"]
    FVS --> FV["finvizfinance"]
    Cal --> RETRY["_get_json_with_retries"]
    RETRY --> INV["Investing.com\nJSON API"]

    style sym fill:#9f9,stroke:#333
    style YFS fill:#cfc,stroke:#333
    style FVS fill:#cfc,stroke:#333
```

---

## 3. Сводка: откуда что приходит (текущий контур)

Одна диаграмма «внешний мир → тип данных» для обзора.

```mermaid
flowchart LR
    subgraph ext["Внешние системы"]
        YF["Yahoo / yfinance"]
        FZ["Finviz"]
        IC["Investing.com API"]
    end

    subgraph out["Модели в domain.py"]
        OHLC["Candle[]"]
        TM["TickerMetrics"]
        ER["Earnings"]
        NA["NewsArticle[]"]
        CE["CalendarEvent[]"]
    end

    YF --> OHLC
    YF --> ER
    YF --> NA
    FZ --> TM
    IC --> CE
```

---

## 4. Целевой контур (ориентир, как в **lse**) — не реализовано

Для следующих итераций: несколько провайдеров новостей/календаря, нормализация, дедуп, запись в БД.

```mermaid
flowchart TB
    subgraph prov["Провайдеры (будущее)"]
        N1["Yahoo news"]
        N2["RSS / NewsAPI / Investing…"]
        C1["Investing JSON"]
        C2["HTML fallback / AV…"]
    end

    subgraph pipe["Общий pipeline"]
        NORM["Нормализация + dedup"]
        KB[("Knowledge base / DB")]
    end

    N1 --> NORM
    N2 --> NORM
    C1 --> NORM
    C2 --> NORM
    NORM --> KB

    style pipe fill:#eef,stroke:#333
```

---

*При изменении модулей в `sources/` имеет смысл обновлять этот файл и [architecture.md](./architecture.md), чтобы схемы оставались правдой.*
