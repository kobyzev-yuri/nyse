# NYSE Signal Bot — документация

Telegram-бот для анализа тикеров из списка `GAME_5M` через полный pipeline:
технический агент → новостной пайплайн (FinBERT + LLM) → торговый сигнал.

---

## Запуск

```bash
cd /media/cnn/home/cnn/lse/nyse
conda run -n py11 python scripts/run_bot.py
```

Требует заполненного `config.env` (см. `config.env.example`).  
Обязательные переменные: `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `HF_TOKEN`.  
Прокси: `TELEGRAM_PROXY=socks5h://127.0.0.1:1080` (если Telegram недоступен напрямую).

---

## Команды

### `/signal TICKER`

Полный pipeline L0–L6 для одного тикера.

**Вывод:**
- Текст в чате: направление (LONG/SHORT/NO TRADE), Entry/TP/SL, Fused bias
- HTML-файл: краткие секции Trade, Fusion, Technical summary, заголовки новостей

**Pipeline:**
```
L0-L1  yfinance + Finviz → TickerData, TickerMetrics
L2     LseHeuristicAgent → TechnicalSignal        ← KERIM_REPLACE
L3     Yahoo News → FinBERT → DraftImpulse
L4     Gate → LLMMode (SKIP/LITE/FULL)
L5     LLM (если FULL/LITE) → AggregatedNewsSignal
L6     TradeBuilder → Trade (Entry/TP/SL)
```

---

### `/scan`

Быстрый технический снапшот всех `GAME_5M` тикеров без LLM (~10 сек).

**Вывод:**
- Текст в чате: таблица `<pre>` с bias/conf/RSI
- HTML-файл: та же таблица в тёмной теме

---

### `/news TICKER`

Заголовки за 48 ч с `cheap_sentiment` (FinBERT / price_pattern_boost).

**Вывод:**
- Текст: список `▲/■/▼ канал score заголовок`
- HTML-файл: полная таблица с summary, временем публикации, каналом

---

### `/news_signal TICKER`

**Debug-команда.** Прогоняет полный pipeline и выдаёт подробный HTML-отчёт
со всеми промежуточными данными. Используется для калибровки и отладки.

**HTML-отчёт (7 секций):**

| # | Секция | Что показывает |
|---|--------|---------------|
| ① | Trade Signal | Entry/TP/SL/conf по шаблону Керима |
| ② | Fusion Breakdown | вклад Tech (55%) и News LLM (45%) |
| ③ | Technical Signal | все 12 score-полей с визуальным баром |
| ④ | Articles + cheap_sentiment | заголовки, канал INC/REG/POL, score, флаг ✓→LLM |
| ⑤ | DraftImpulse | per-channel: count, weight sum, bias, max\|sentiment\| |
| ⑥ | Gate Decision | GateContext vs пороги, LLMMode + причина на русском |
| ⑦ | AggregatedNewsSignal | aggregate + per-article LLM (sentiment/impact/relevance/surprise) |

Файл: `debug_TICKER_YYYY-MM-DD_HH-MM.html`

---

### `/status`

Статус торговой сессии NYSE/NASDAQ с текущим временем ET.
Показывает: основная / премаркет / постмаркет / закрыто, время до открытия/закрытия.

### `/help`

Список команд с описанием. ### `/start`

Приветствие.

---

## Архитектура

```
scripts/run_bot.py          ← точка входа, long-polling
bot/nyse_bot.py             ← хендлеры команд + воркеры
  ├── _load_market_data()   ← общий хелпер: yfinance + Finviz
  ├── _worker_scan()        → (short_text, html)
  ├── _worker_signal()      → (short_text, html)
  ├── _worker_news()        → (short_text, html)
  ├── _worker_news_signal() → (short_text, html)  ← debug
  └── _worker_status()      → str

pipeline/
  ├── debug_runner.py       ← PipelineDebugTrace + run_debug_pipeline()
  ├── html_report.py        ← build_*_html() функции
  ├── trade_builder.py      ← TradeBuilder, FusedBias, neutral_calendar_signal
  ├── telegram_format.py    ← format_trade(), format_news_list()
  ├── gates.py              ← decide_llm_mode()
  ├── draft.py              ← draft_impulse(), MultiTickerGateSession
  ├── sentiment.py          ← enrich_cheap_sentiment(), price_pattern_boost
  ├── news_signal_runner.py ← run_news_signal_pipeline()
  └── types.py              ← PROFILE_GAME5M, PROFILE_CONTEXT, ThresholdConfig
```

### Паттерн воркера

Все тяжёлые операции (yfinance, Finviz, FinBERT, LLM) выполняются синхронно
в thread executor, чтобы не блокировать event loop Telegram:

```python
result = await loop.run_in_executor(None, partial(_worker_signal, ticker_str))
```

Каждый воркер возвращает `(short_text: str, html_content: str)`:
- `short_text` → `reply_text(parse_mode=HTML)` в чат
- `html_content` → `reply_document(BytesIO(...), filename=...)` следом

---

## Конфигурация

| Переменная | Описание |
|------------|---------|
| `TELEGRAM_BOT_TOKEN` | токен от @BotFather |
| `TELEGRAM_PROXY` | `socks5h://host:port` — прокси для Telegram API |
| `OPENAI_API_KEY` | ключ для LLM (L5 pipeline) |
| `OPENAI_MODEL` | модель, дефолт `gpt-5.4-mini` |
| `OPENAI_TEMPERATURE` | `0` — детерминированный structured output |
| `HF_TOKEN` | Hugging Face для загрузки FinBERT |
| `NYSE_GAME5M_TICKERS` | список через запятую, дефолт `SNDK,NBIS,ASML,MU,LITE,CIEN` |
| `NYSE_CONTEXT_TICKERS` | контекстные тикеры (SMH, QQQ) |
| `NYSE_LLM_CACHE_TTL_SEC` | TTL кэша LLM-ответов, дефолт 3600 |

---

## Прокси

Если `api.telegram.org` недоступен напрямую — нужен SOCKS5-прокси.

```bash
# Проверка доступности
curl --socks5-hostname 127.0.0.1:1080 https://api.telegram.org/bot<TOKEN>/getMe

# В config.env
TELEGRAM_PROXY=socks5h://127.0.0.1:1080
```

Используется `httpx==0.27.2` (версия 0.28+ требует отдельной установки `socksio`).
При проблемах: `pip install "httpx==0.27.2" socksio`.

---

## KERIM_REPLACE — маркеры для интеграции

В коде расставлены комментарии `# KERIM_REPLACE` в местах, где предполагается
замена baseline-агента на ML-агент Керима:

### `bot/nyse_bot.py` — `_worker_scan` и `_worker_signal`

```python
# KERIM_REPLACE: заменить LseHeuristicAgent на KerimsAgent:
#   from pystockinvest.agent.market.agent import Agent as KerimsAgent
#   from pipeline.llm_factory import get_chat_model
#   agent = KerimsAgent(llm=get_chat_model())
#   Интерфейс predict(ticker, ticker_data, metrics) → TechnicalSignal идентичен.
agent = LseHeuristicAgent()
```

### `pipeline/debug_runner.py` — `run_debug_pipeline`

Та же замена, плюс опционально передать кастомный `profile`:

```python
trace = run_debug_pipeline(
    ticker, ticker_data, metrics_list,
    profile=PROFILE_GAME5M,   # или PROFILE_CONTEXT для крупных тикеров
    settings=oai,
)
```

### `pipeline/trade_builder.py` — веса fusion

```python
# KERIM_REPLACE: TECH_WEIGHT и NEWS_WEIGHT → обучаемые параметры
TECH_WEIGHT = 0.55
NEWS_WEIGHT = 0.45
```

### `TechnicalAgentProtocol`

Формальный контракт агента — `pipeline/technical/protocol.py`:

```python
class TechnicalAgentProtocol(Protocol):
    def predict(
        self,
        ticker: Ticker,
        ticker_data: List[TickerData],
        metrics: List[TickerMetrics],
    ) -> TechnicalSignal: ...
```

`LseHeuristicAgent` и `KerimsAgent` оба соответствуют этому протоколу.
Замена прозрачна для `TradeBuilder` и `_worker_signal`.

---

## Добавление нового тикера

1. Добавить в `domain.py::Ticker` enum
2. Добавить в `NYSE_GAME5M_TICKERS` или `NYSE_CONTEXT_TICKERS` в `config.env`
3. Запустить `/news_signal НОВЫЙ_ТИКЕР` для оценки объёма новостного покрытия
4. При необходимости откалибровать профиль (см. `docs/calibration.md`, Сценарий E)

---

## Связанные документы

- `docs/calibration.md` — пороги Gate, журнал прогонов, сценарии перекалибровки
- `docs/news_pipeline_hierarchy.md` — уровни L0–L6 pipeline
- `docs/architecture.md` — общая архитектура nyse
- `docs/configuration.md` — все переменные `config.env`
