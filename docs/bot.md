# NYSE Signal Bot — документация

Telegram-бот для анализа тикеров из списка `GAME_5M` через pipeline:
технический агент → новостной пайплайн (FinBERT + LLM) → при необходимости торговое решение.

---

## Запуск

```bash
cd /path/to/nyse   # корень репозитория nyse
conda run -n py11 python scripts/run_bot.py
```

Требует заполненного `config.env` (см. `config.env.example`).  
Обязательные переменные: `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `HF_TOKEN`.  
Прокси: `TELEGRAM_PROXY=socks5h://127.0.0.1:1080` (если Telegram недоступен напрямую).

---

## Команды

### `/trade TICKER`

**Агрегированное решение для входа:** полный pipeline L0–L6 для одного тикера (то, что раньше выдавалось командой `/signal`).

**Вывод:**
- Текст в чате: направление (LONG/SHORT/NO TRADE), Entry/TP/SL, Fused bias
- HTML-файл `trade_TICKER_YYYY-MM-DD_HH-MM.html`: Trade, Fusion, макро-календарь (как у гейта), блоки новостей INC/POL и REG, технический и LLM-сводки

**Pipeline:**
```
L0-L1  yfinance + Finviz → TickerData, TickerMetrics
L2     LseHeuristicAgent / LlmTechnicalAgent → TechnicalSignal
L3     Yahoo News → FinBERT → DraftImpulse
L4     Gate → LLMMode (SKIP/LITE/FULL); календарь HIGH влияет на FULL
L5     LLM (если FULL/LITE) → AggregatedNewsSignal
L6     TradeBuilder → Trade (Entry/TP/SL)
```

---

### `/signal TICKER`

**Полный отчёт по пайплайну (отладка / калибровка).** То же, что раньше команда `/news_signal`: прогон `run_debug_pipeline` и подробный HTML со всеми промежуточными данными (секции ①–⑦).

**HTML-файл:** `signal_TICKER_YYYY-MM-DD_HH-MM.html` (заголовок окна: «Signal (full)»).

**Совместимость:** команда `/news_signal` зарегистрирована как алиас и вызывает тот же обработчик, что и `/signal`.

---

### `/scan`

Быстрый технический снапшот всех `GAME_5M` тикеров без LLM (~10 сек).

**Вывод:**
- Текст в чате: таблица `<pre>` с bias/conf/RSI
- HTML-файл: та же таблица в тёмной теме

---

### `/news TICKER`

**Новости, геополитика (каналы INC/REG/POL) и макро-календарь** — без торгового пайплайна (без L2–L6, без Entry/TP/SL).

Окно заголовков задаётся `NYSE_NEWS_LOOKBACK_NEWS_HOURS` (по умолчанию 48 ч).

**Вывод:**
- Текст: список `▲/■/▼ канал score заголовок`
- HTML-файл `news_TICKER_...`: календарь (ecalendar), затем блоки обычных новостей и REG; в таблицах может отображаться `provider_id`

---

### `/status`

Статус торговой сессии NYSE/NASDAQ с текущим временем ET.  
Показывает: основная / премаркет / постмаркет / закрыто, время до открытия/закрытия.

### `/help`

Список команд с описанием.

### `/start`

Приветствие.

---

## Архитектура

```
scripts/run_bot.py          ← точка входа, long-polling
bot/nyse_bot.py             ← хендлеры команд + воркеры
  ├── _load_market_data()   ← общий хелпер: yfinance + Finviz
  ├── _worker_scan()        → (short_text, html)
  ├── _worker_trade()       → (short_text, html)   ← /trade, агрегат для входа
  ├── _worker_signal()      → (short_text, html)   ← /signal, полный L0–L6 HTML
  ├── _worker_news()        → (short_text, html)   ← /news, без trade pipeline
  └── _worker_status()      → str

pipeline/
  ├── debug_runner.py       ← PipelineDebugTrace + run_debug_pipeline()
  ├── html_report.py        ← build_trade_html(), build_news_html(), build_debug_report_html()
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
result = await loop.run_in_executor(None, partial(_worker_trade, ticker_str))
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
| `NYSE_NEWS_LOOKBACK_SIGNAL_HOURS` | окно новостей для `/trade`, дефолт 72 |
| `NYSE_NEWS_LOOKBACK_NEWS_HOURS` | окно для `/news`, дефолт 48 |
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

### `bot/nyse_bot.py` — `_worker_scan` и `_worker_trade`

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

### `pipeline/trade_builder.py` — слияние (1:1 с pystockinvest)

Константы **`W_TECH` / `W_NEWS` / `W_CAL`** (0.55 / 0.30 / 0.15), формула **`_final_confidence`**, вход **LIMIT/MARKET**, **TP/SL** через ATR и `volatility_regime` — как в **`pystockinvest/agent/trade.py`**.  
`KERIM_REPLACE`: в будущем веса можно сделать обучаемыми в агенте Керима; до тех пор не менять без синхронизации с pystockinvest.

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
Замена прозрачна для `TradeBuilder` и `_worker_trade`.

---

## Добавление нового тикера

1. Добавить в `domain.py::Ticker` enum
2. Добавить в `NYSE_GAME5M_TICKERS` или `NYSE_CONTEXT_TICKERS` в `config.env`
3. Запустить `/signal НОВЫЙ_ТИКЕР` (полный HTML) или `/news НОВЫЙ_ТИКЕР` для оценки объёма новостного покрытия
4. При необходимости откалибровать профиль (см. `docs/calibration.md`, Сценарий E)

---

## Промпты LLM и соответствие pystockinvest

| Назначение | NYSE | pystockinvest | Совпадение |
|------------|------|---------------|------------|
| Новостной structured signal (L5 FULL) | `pipeline/news_signal_prompt.py` (`SYSTEM_PROMPT`, `USER_PROMPT_TEMPLATE`) | `agent/news/signal.py` | **Да** (тексты как в signal.py; `PROMPT_VERSION=v2` — смена ключа кэша) |
| Lite-дайджест по заголовкам (LITE) | `pipeline/llm_digest.py` `build_digest_messages` | отдельного аналога нет | Только в NYSE (микро-промпт JSON bias/summary) |
| Отбор статей перед LLM | `pipeline/llm_batch_plan.py` (правила + \|sentiment\|) | `agent/news/selection.py` (LLM) | **Нет**: разная стратегия (NYSE без LLM-selection) |
| Технический агент | `LseHeuristicAgent` (эвристики, без LLM) | `agent/market/agent.py` (LLM + structured) | **Нет промпта в NYSE**; замена на `KerimsAgent` — см. `KERIM_REPLACE` |
| Календарь | `neutral_calendar_signal()` (заглушка) | `agent/calendar/agent.py` (LLM) | **Нет промпта в NYSE** до появления CalendarAgent |

---

## Связанные документы

- `docs/calibration.md` — пороги Gate, журнал прогонов, сценарии перекалибровки
- `docs/news_pipeline_hierarchy.md` — уровни L0–L6 pipeline
- `docs/architecture.md` — общая архитектура nyse
- `docs/configuration.md` — все переменные `config.env`
