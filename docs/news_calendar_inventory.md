# Новости и календарь: реализованный контур

Документ фиксирует **реализованное** состояние источников, типизации и контракта домена.  
Гипотезы и «кандидаты на добавление» — закрыты; раздел «план» — только незакрытые задачи.

---

## 1. Источники данных: что реализовано

| Область | Модуль | Провайдер | Выход |
|--------|--------|-----------|-------|
| Новости по тикеру | `sources/news.py` | Yahoo / yfinance | `NewsArticle[]` |
| Новости + entity sentiment | `sources/news_marketaux.py` | Marketaux | `NewsArticle[]` с `raw_sentiment` |
| Тематические новости | `sources/news_newsapi.py` | NewsAPI v2 | `NewsArticle[]` |
| Новости + sentiment | `sources/news_alphavantage.py` | Alpha Vantage | `NewsArticle[]` с `raw_sentiment` |
| Макро / ЦБ / агентства | `sources/news_rss.py` | RSS / Atom | `NewsArticle[]` (ticker=GENERAL) |
| Макро-календарь | `sources/ecalendar.py` | Investing.com JSON | `CalendarEvent[]` |
| Свечи / цена | `sources/candles.py` | yfinance | `Candle[]` |
| Скринер-метрики | `sources/metrics.py` | Finviz | `TickerMetrics` |
| Earnings | `sources/earnings.py` | yfinance | `Earnings` |

**Investing HTML-лента** — не реализована (хрупко, дублирует Marketaux/Yahoo).

---

## 2. Доменная модель: реализованные типы

### `NewsArticle` (`domain.py`)

| Поле | Тип | Примечание |
|------|-----|-----------|
| `ticker` | `Ticker` | включая `Ticker.GENERAL` для нетикерных лент |
| `title`, `summary` | `str` | |
| `timestamp` | `datetime` (UTC) | |
| `link` | `Optional[str]` | для дедупликации |
| `publisher` | `Optional[str]` | |
| `provider_id` | `Optional[str]` | `"yfinance"`, `"marketaux"`, `"newsapi"` и т.д. |
| `raw_sentiment` | `Optional[float]` | [−1, 1]; от Marketaux / Alpha Vantage |
| `cheap_sentiment` | `Optional[float]` | [−1, 1]; заполняется на уровне 2 |

### `NewsSignal` и `AggregatedNewsSignal` (`domain.py`)

Реализованы как DTO уровня 5, согласованы с `pystockinvest/agent/models.py`:

```python
@dataclass
class NewsSignal:
    sentiment: float            # [−1, 1]
    impact_strength: NewsImpact      # LOW | MODERATE | HIGH
    relevance: NewsRelevance         # LOW | MEDIUM | HIGH
    surprise: NewsSurprise           # NONE | MINOR | SIGNIFICANT | MAJOR
    time_horizon: NewsTimeHorizon    # INTRADAY | SHORT | MEDIUM | LONG
    confidence: float           # [0, 1]

@dataclass
class AggregatedNewsSignal:
    bias: float
    confidence: float
    summary: list[str]
    items: list[NewsSignal]
```

### `NewsImpactChannel` (`pipeline/types.py`)

| Канал | Смысл | Как назначается |
|-------|-------|----------------|
| `INCREMENTAL` | Обычный рыночный поток | По умолчанию |
| `REGIME` | Геополитика, санкции, системные шоки | Словари: `war`, `sanctions`, `embargo`, … |
| `POLICY_RATES` | Решения ЦБ, ставки, QE/QT | Словари: `Fed`, `FOMC`, `rate hike`, … |

Реализовано в `pipeline/channels.py`. Каналы **не смешиваются** при агрегации `DraftImpulse`.

### `CalendarEvent` (`domain.py`)

| Поле | Тип |
|------|-----|
| `time` | `datetime` (UTC) |
| `currency` | `Currency` |
| `importance` | `CalendarEventImportance`: LOW / MEDIUM / HIGH |
| `actual`, `forecast`, `previous` | `Optional[str]` |

---

## 3. Канал воздействия: реализованная логика (§5.4)

Три канала ортогональны провайдеру и тикеру:

| Канал | Типичный эффект | В коде |
|-------|----------------|--------|
| **INCREMENTAL** | Основной новостной импульс; вес по relevance × impact × horizon × confidence | `pipeline/news_signal_aggregator.py` |
| **REGIME** | Повышенный `regime_stress`; при `> T2` → гейт принудительно `FULL`; не смешивается с INCREMENTAL | `pipeline/draft.py`, `pipeline/gates.py` |
| **POLICY_RATES** | Отдельный `policy_stress`; частично перекрывается с CalendarEvent HIGH | `pipeline/draft.py` |

`regime_stress > PROFILE_GAME5M.regime_stress_min (0.05)` → `regime_present=True` → возможен `FULL`.

---

## 4. Веса в агрегаторе: реализовано (§5.5)

В `pipeline/news_signal_aggregator.py`:

```
relevance_weight:  LOW=0.5, MEDIUM=1.0, HIGH=1.5
impact_weight:     LOW=0.5, MODERATE=1.0, HIGH=2.0
horizon_weight:    INTRADAY=1.0, SHORT=0.8, MEDIUM=0.6, LONG=0.4
confidence:        умножается на итоговый вес статьи
```

`AggregatedNewsSignal.bias` = взвешенная сумма `sentiment × weights` / `Σ weights`.

---

## 5. Что остаётся (план)

| Задача | Примечание |
|--------|-----------|
| **`regime_overhang`** как явный член формулы слияния с техническим сигналом | При `REGIME`-статьях снижать `confidence` итоговой сделки или вводить отдельный вес |
| Отдельный короткий LLM-промпт для `REGIME` / `POLICY_RATES` батча | Сейчас они попадают в общий `build_signal_messages` |
| `provider_id` в фильтре при дедупликации (приоритет провайдеров) | Сейчас дедуп только по URL-хешу |
| Связь `CalendarEvent` с новостью (пересечение по времени ± N часов) | Низкий приоритет |
