# Потоки данных nyse pipeline

Диаграммы в формате **Mermaid** — корректно отображаются в GitHub preview.

---

## 1. Полный поток: от источника к сделке

```mermaid
flowchart TB
    subgraph SRC["Источники данных"]
        YF["Yahoo / yfinance\nNewsArticle[]"]
        MX["Marketaux\n+ raw_sentiment"]
        NA["NewsAPI / RSS\nAlpha Vantage"]
        CAL["Investing.com\nCalendarEvent[]"]
        TECH["TA-модели / CatBoost\nOHLCV + Metrics"]
    end

    subgraph PIPE["nyse: News Pipeline (уровни 0–5)"]
        L0["Уровень 0\nIngest: дедуп, окно\npipeline/ingest.py"]
        L1["Уровень 1\nNewsImpactChannel\npipeline/channels.py"]
        L2["Уровень 2\ncheap_sentiment\npipeline/sentiment.py"]
        L2B["price_pattern_boost\n'Jumped 15%' → +0.8"]
        L3["Уровень 3\nDraftImpulse\npipeline/draft.py"]
        L4["Уровень 4 — ГЕЙТ\ndecide_llm_mode\npipeline/gates.py"]
        SKIP["SKIP\nиспользовать draft_bias"]
        LITE["LITE\nllm_digest.py\nкраткий дайджест"]
        L5["Уровень 5 — LLM\nrun_news_signal_pipeline\npipeline/news_signal_runner.py"]
        AGG["AggregatedNewsSignal\nbias · confidence · summary"]
    end

    subgraph PSI["pystockinvest: Orchestrator"]
        TA["TechnicalAgent\nTechnicalSignal"]
        CA["CalendarAgent\nCalendarSignal"]
        TB["TradeBuilder\nfinal_bias =\n0.55·tech + 0.30·news + 0.15·cal"]
    end

    subgraph LSE["lse: Исполнение"]
        GM["GAME_5M\nCatBoost + позиция"]
        DB[("PostgreSQL\nPositions · KB")]
        TG["Telegram Bot"]
    end

    YF & MX & NA --> L0
    CAL --> L4
    L0 --> L1 --> L2
    L2 <--> L2B
    L2 --> L3 --> L4
    L4 --> SKIP & LITE & L5
    SKIP --> AGG
    LITE --> AGG
    L5 --> AGG

    TECH --> TA
    CAL --> CA
    AGG --> TB
    TA --> TB
    CA --> TB
    TB --> GM
    GM --> DB
    GM --> TG

    style L4 fill:#ffe4b5,stroke:#d4a000
    style L5 fill:#d4edda,stroke:#28a745
    style AGG fill:#cce5ff,stroke:#004085
    style TB fill:#f8d7da,stroke:#721c24
```

---

## 2. Детализация уровня 2: cheap_sentiment

```mermaid
flowchart LR
    ART["NewsArticle\ntitle + summary"]

    subgraph S2["pipeline/sentiment.py"]
        RAW{"raw_sentiment\nот API?"}
        CLIP["clip(−1, 1)"]
        FB["FinBERT\nProsusAI/finbert\nlокально, TTL-кэш"]
        PPB["price_pattern_boost\n'jumped X%'\n'sinks X%'"]
        FLOOR{"|boost| >\n|finbert|?"}
        OUT["cheap_sentiment\n∈ [−1, 1]"]
    end

    ART --> RAW
    RAW -- да --> CLIP --> OUT
    RAW -- нет --> FB
    ART --> PPB
    FB --> FLOOR
    PPB --> FLOOR
    FLOOR -- да --> OUT
    FLOOR -- нет --> OUT

    style PPB fill:#fff3cd,stroke:#856404
    style FLOOR fill:#d1ecf1,stroke:#0c5460
```

**Масштаб price_pattern_boost:**

| Движение | boost |
|----------|-------|
| ≥ 20% | ±1.0 |
| ≥ 10% | ±0.8 |
| ≥  5% | ±0.6 |
| ≥  2% | ±0.4 |
| < 2%  | ±0.2 |

---

## 3. Детализация уровня 4: решение гейта

```mermaid
flowchart TB
    IN["DraftImpulse\n+ GateContext\n+ ThresholdConfig"]

    C1{"calendar_high_soon?"}
    C2{"regime_present AND\nrule_conf ≥ T2?"}
    C3{"|bias| ≥ T1×2?"}
    C4{"|bias| < T1 AND\nno REGIME?"}
    C5{"article_count > N?"}

    FULL["FULL\nrun_news_signal_pipeline\n(Kerima LLM)"]
    LITE["LITE\nllm_digest\n(краткий дайджест)"]
    SKIP["SKIP\nиспользовать draft_bias"]

    IN --> C1
    C1 -- да --> FULL
    C1 -- нет --> C2
    C2 -- да --> FULL
    C2 -- нет --> C3
    C3 -- да --> FULL
    C3 -- нет --> C4
    C4 -- да --> SKIP
    C4 -- нет --> C5
    C5 -- да --> LITE
    C5 -- нет --> LITE

    style FULL fill:#d4edda,stroke:#28a745
    style LITE fill:#fff3cd,stroke:#856404
    style SKIP fill:#f8d7da,stroke:#721c24
```

**Профили ThresholdConfig** (откалибровано 2026-04-06):

| Профиль | T1 | T1×2 | N | regime_stress_min |
|---------|----|------|---|-------------------|
| `PROFILE_GAME5M` | 0.12 | 0.24 | 8 | 0.05 |
| `PROFILE_CONTEXT` | 0.20 | 0.40 | 15 | 0.05 |

---

## 4. Технический сигнал Kerima (TechnicalSignal)

```mermaid
flowchart LR
    subgraph IN["Входные данные"]
        OHLCV["OHLCV 5m/1h/1d\nTickerData[]"]
        MET["TickerMetrics\nRSI, ATR, SMA, beta…"]
        CORR["Матрица корреляций\nSMH, QQQ, VIX, нефть…"]
    end

    subgraph TS["TechnicalSignal (pystockinvest)"]
        BIAS["bias ∈ [−1, +1]"]
        SCORES["trend_score\nmomentum_score\nmean_reversion_score\nbreakout_score"]
        RISK["volatility_regime\nrelative_strength_score\nmarket_alignment_score\nexhaustion_score\nsupport_resistance_pressure"]
        TRADE["tradeability_score\n< 0.40 → не входить"]
        CONF["confidence ∈ [0, 1]"]
    end

    OHLCV & MET & CORR --> BIAS & SCORES & RISK & TRADE & CONF

    style TRADE fill:#f8d7da,stroke:#721c24
    style BIAS fill:#cce5ff,stroke:#004085
```

---

## 5. TradeBuilder: финальное решение

```mermaid
flowchart TB
    TS["TechnicalSignal\nbias, confidence\ntradeability_score"]
    NS["AggregatedNewsSignal\nbias, confidence\n(или 0.0 если SKIP)"]
    CS["CalendarSignal\nbroad_equity_bias\nupcoming_event_risk, confidence"]

    subgraph TB_BOX["TradeBuilder (pystockinvest/agent/trade.py)"]
        FBIAS["final_bias =\n0.55 × tech_bias\n+ 0.30 × news_bias\n+ 0.15 × cal_bias"]
        FCONF["confidence =\n(0.50 × tech_conf\n+ 0.30 × news_conf\n+ 0.20 × cal_conf\n+ agreement_bonus)\n× (1 − 0.35 × event_risk)"]
        CHECK{"tradeability\n≥ 0.40?"}
        POS["Position\nsize, stop, take"]
        NONE["PositionType.NONE"]
    end

    TRADE["domain.Trade\nentry_type, position\ntechnical/news/calendar summary"]

    TS & NS & CS --> FBIAS & FCONF
    FBIAS --> CHECK
    CHECK -- да --> POS --> TRADE
    CHECK -- нет --> NONE --> TRADE

    style FBIAS fill:#d4edda,stroke:#28a745
    style FCONF fill:#d4edda,stroke:#28a745
    style TRADE fill:#cce5ff,stroke:#004085
```

---

## 6. Источники данных (текущий контур)

```mermaid
flowchart LR
    subgraph EXT["Внешние системы"]
        YF["Yahoo / yfinance"]
        FZ["Finviz"]
        IC["Investing.com API"]
        MX2["Marketaux"]
        NW["NewsAPI / RSS\nAlpha Vantage"]
    end

    subgraph DOM["domain.py"]
        OHLC["Candle[]"]
        TM["TickerMetrics"]
        ER["Earnings"]
        NA2["NewsArticle[]"]
        CE["CalendarEvent[]"]
    end

    YF --> OHLC & ER & NA2
    FZ --> TM
    IC --> CE
    MX2 & NW --> NA2

    style DOM fill:#eef,stroke:#333
```

---

*Схемы — живой документ. При изменении весов TradeBuilder, порогов или новых модулей — обновлять здесь и в `architecture.md`.*
