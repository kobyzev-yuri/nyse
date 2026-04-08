# NYSE Signal Bot — документация

Telegram-бот для анализа тикеров из списка `GAME_5M` через полный pipeline:
технический агент → новостной пайплайн (FinBERT + LLM) → торговый сигнал.

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

### `/signal TICKER`

Полный pipeline L0–L6 для одного тикера.

**Вывод:**
- Текст в чате: направление (LONG/SHORT/NO TRADE), Entry/TP/SL, Fused bias
- HTML-файл: краткие секции Trade, Fusion, Technical summary, заголовки новостей

**Pipeline:**
```
L0-L1  yfinance + Finviz → TickerData, TickerMetrics
L2     LseHeuristicAgent или LlmTechnicalAgent (NYSE_LLM_TECHNICAL=1) → TechnicalSignal
L3     Yahoo News → FinBERT → DraftImpulse
L4     Gate (+ calendar_high_soon из ecalendar) → LLMMode (SKIP/LITE/FULL)
L5     LLM новостей (если FULL/LITE) → AggregatedNewsSignal
L6     TradeBuilder (+ CalendarLlmAgent при NYSE_LLM_CALENDAR=1) → Trade
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
| ② | Fusion Breakdown | вклад Tech (55%), News LLM (30%), Calendar (15%) — как в `pystockinvest/agent/trade.py` |
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
  ├── calendar_signal_runner.py, calendar_llm_agent.py
  ├── technical_signal_runner.py, technical/llm_technical_agent.py
  ├── llm_cache.py, lc_shim.py  ← кэш completion, shim сообщений LangChain
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
| `NYSE_LLM_CACHE_TTL_SEC` | TTL кэша LLM-ответов (новости, техника, календарь), см. `llm_cache.py` |
| `NYSE_LLM_TECHNICAL` | `1` / `true` — structured LLM для техники (`LlmTechnicalAgent`) |
| `NYSE_LLM_CALENDAR` | `1` / `true` — structured LLM для календаря (`CalendarLlmAgent`) |
| `NYSE_CALENDAR_LLM_BATCH_SIZE` | необязательно: размер батча событий календаря (как в pystockinvest) |
| `TELEGRAM_SIGNAL_CHAT_ID` | chat для интеграционных тестов бота (`tests/integration/test_telegram_bot_smoke.py`) |

**Экономия токенов:** гейт L4 (`SKIP` / `LITE` / `FULL`) не вызывает полный news-LLM при слабом сигнале; ответы кэшируются по хешу промпта + модели (`cache_key_llm`). Календарь: при chunked-событиях ключ включает номер батча, чтобы не смешивать ответы. См. `docs/configuration.md`.

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

## Соответствие pystockinvest и TradeBuilder

- **Слияние сигналов** — `pipeline/trade_builder.py`: веса **`W_TECH` / `W_NEWS` / `W_CAL`**, `_final_confidence`, LIMIT/MARKET, TP/SL — как **`pystockinvest/agent/trade.py`**. Менять веса только синхронно с pystockinvest.
- **Технический агент** — `TechnicalAgentProtocol` (`pipeline/technical/protocol.py`): реализуют `LseHeuristicAgent`, `LlmTechnicalAgent`, агент market в pystockinvest.
- **Debug** — `run_debug_pipeline(..., profile=PROFILE_GAME5M, settings=oai)` в `pipeline/debug_runner.py`.

---

## Добавление нового тикера

1. Добавить в `domain.py::Ticker` enum
2. Добавить в `NYSE_GAME5M_TICKERS` или `NYSE_CONTEXT_TICKERS` в `config.env`
3. Запустить `/news_signal НОВЫЙ_ТИКЕР` для оценки объёма новостного покрытия
4. При необходимости откалибровать профиль (см. `docs/calibration.md`, Сценарий E)

---

## Промпты LLM и соответствие pystockinvest

| Назначение | NYSE | pystockinvest | Совпадение |
|------------|------|---------------|------------|
| Новостной structured signal (L5 FULL) | `pipeline/news_signal_prompt.py` | `agent/news/signal.py` | **Да**; `PROMPT_VERSION` в промпте — смена ключа кэша |
| Lite-дайджест (LITE) | `pipeline/llm_digest.py` | — | Только NYSE (JSON bias/summary) |
| Отбор батча перед LLM | `pipeline/llm_batch_plan.py` | `agent/news/selection.py` (LLM) | NYSE: правила + \|sentiment\|, без LLM-selection |
| Техника | `LseHeuristicAgent` / `LlmTechnicalAgent` + `technical_signal_*` | `agent/market/agent.py` | DTO/промпты как в pystockinvest |
| Календарь | `neutral_*` или `CalendarLlmAgent` + `calendar_signal_*` | `agent/calendar/agent.py` | DTO/промпты как в pystockinvest |

---

## Связанные документы

- `docs/calibration.md` — пороги Gate, журнал прогонов, сценарии перекалибровки
- `docs/news_pipeline_hierarchy.md` — уровни L0–L6 pipeline
- `docs/architecture.md` — общая архитектура nyse
- `docs/configuration.md` — все переменные `config.env`
