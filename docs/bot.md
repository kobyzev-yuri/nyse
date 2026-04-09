# NYSE Signal Bot — документация

Telegram-бот для анализа тикеров из списка `GAME_5M` через pipeline:
технический агент → новостной пайплайн (FinBERT + LLM) → при необходимости торговое решение.

---

## Поток расчётов: от данных до решения о входе

Ниже — одна цепочка «своими словами»: что считается раньше, что позже, и какие числа реально попадают в сделку. Развёрнутая версия с **реальным примером MU** — в [`docs/СвоимиСловами.md`](СвоимиСловами.md); тот же прогон как статический HTML (все блоки ①–⑦) — файл [`docs/examples/signal_MU_2026-04-08_17-52.html`](examples/signal_MU_2026-04-08_17-52.html) (на GitHub он виден как **исходный код**, не как страница; **просмотр с рендером:** [HTMLPreview](https://htmlpreview.github.io/?https://raw.githubusercontent.com/kobyzev-yuri/nyse/main/docs/examples/signal_MU_2026-04-08_17-52.html), см. [`docs/examples/README.md`](examples/README.md)). Если нужно сместить поведение бота, почти всегда ищите именованные константы или профиль в указанных файлах (а не «магические» литералы в середине функций).

### L0–L1: рыночный контекст

Подтягиваются свечи (yfinance) и по возможности метрики (Finviz) для целевого тикера и контекста (например SMH, QQQ). Без этого пайплайн дальше не поедет. Это сырьё для цен, ATR, RSI и т.д.

### L2: технический сигнал

Агент (по умолчанию эвристика `LseHeuristicAgent`, опционально structured LLM при `NYSE_LLM_TECHNICAL`) выдаёт **`TechnicalSignal`**: в частности **`bias`** ∈ [-1,1], **`confidence`**, **`tradeability_score`** (насколько «тянется» заявка на сделку) и сводные строки в `summary`.  
**`tradeability_score` нигде не смешивается с новостями** — он участвует только в финальном гейте L6.

### L3: новости «по скорам», без агрегатора LLM

Загружаются заголовки; на каждую статью вешается **`cheap_sentiment`** (FinBERT / API / price_pattern) и канал INC / REG / POL. Из этого строится **`DraftImpulse`** (взвешенные средние по каналам с затуханием по времени) и один скаляр **`draft_bias`**.  
**Важно:** `draft_bias` нужен **гейту L4** (решить, вызывать ли дорогой LLM по новостям и в каком режиме). Он **не** умножается на 30% в формуле Fusion — в Fusion идёт другой объект (см. L5).

### L4: гейт

По `draft_bias`, признаку режима/стресса из черновика, числу статей, календарю HIGH в окне и порогам профиля **`PROFILE_GAME5M`** (`pipeline/types.py`, `ThresholdConfig`) выбирается **`LLMMode`**: SKIP / LITE / FULL.  
В **`run_news_signal_pipeline`** structured LLM по новостям запускается только в режиме **FULL**; при **SKIP** и **LITE** возвращается нейтральный **`AggregatedNewsSignal`** (bias 0) — тогда вклад News в Fusion нулевой, даже если `draft_bias` был выразительным.

### L5: новостной bias для Fusion

Если сработал **FULL**, модель по батчу статей отдаёт structured-поля (sentiment, relevance, impact, horizon, confidence). **`aggregate_news_signals`** (`pipeline/news/news_signal_aggregator.py`; shim: `pipeline/news_signal_aggregator.py`) считает взвешенное среднее sentiment с весами по relevance/impact/horizon/confidence — это и есть **`AggregatedNewsSignal.bias`** и **`confidence`**, которые попадают в сделку. Текстовые строки summary в отчёте — человекочитаемое повторение этих двух чисел.

### L6: сплав и решение о входе

**`TradeBuilder`** (`pipeline/trade/trade_builder.py`; shim: `pipeline/trade_builder.py`) считает  
**`final_bias` = `W_TECH`×tech.bias + `W_NEWS`×news.bias + `W_CAL`×calendar.broad_equity_bias**  
(константы **`W_TECH` / `W_NEWS` / `W_CAL`** — как в `pystockinvest/agent/trade.py`). Календарь без LLM часто нейтрален (bias 0), но таблица макро-событий всё равно влияет на гейт L4.

Отдельно считается **`_final_confidence`** (смесь conf техники, новостей, календаря и штраф за календарный риск) — она попадает в позицию как уверенность сделки.

**Решение LONG / SHORT / NO TRADE** — только по правилам **`_build_position`**:  
1) **`tradeability_score` ≥ `MIN_TRADEABILITY_FOR_POSITION`** (по умолчанию 0.40);  
2) **`final_bias` > `MIN_ABS_FINAL_BIAS_FOR_POSITION`** для LONG или **< −`MIN_ABS_FINAL_BIAS_FOR_POSITION`** для SHORT (по умолчанию ±0.20).  
Иначе позиции нет (**NO TRADE**).

Тип входа LIMIT/MARKET и уровни TP/SL считаются тем же билдером (ATR, волатильность, новости, календарный риск) — см. `pipeline/trade/trade_builder.py`.

### Где править числа

| Назначение | Где смотреть |
|------------|----------------|
| Веса Fusion 55/30/15, пороги входа L6, LIMIT/MARKET, TP/SL | `pipeline/trade/trade_builder.py` (`W_*`, `MIN_*`, логика `_entry_type` / `_risk_levels`) |
| Пороги гейта L4 (t1, t2, max статей FULL, regime_min) | `pipeline/types.py` — `PROFILE_GAME5M`, `ThresholdConfig` |
| Веса строк в L5-агрегаторе новостей | `pipeline/news/news_signal_aggregator.py` |
| Затухание статей по времени в L3 | `pipeline/news/draft.py` (`draft_impulse`, half-life) |
| Окно HIGH календаря для гейта | `config.env` — `NYSE_CALENDAR_HIGH_*`, см. `config_loader` |
| Включение LLM-техники / календаря | `config.env` — `NYSE_LLM_TECHNICAL`, `NYSE_LLM_CALENDAR` |

Синхронизация с проектом **pystockinvest**: веса и пороги входа в `pipeline/trade/trade_builder.py` задуманы как зеркало `pystockinvest/agent/trade.py`; менять их имеет смысл согласованно в обоих местах.

---

## Запуск

```bash
cd /path/to/nyse   # корень репозитория nyse
conda run -n py11 python scripts/run_bot.py
```

Требует заполненного `config.env` (см. `config.env.example`).  
Обязательные переменные: `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `HF_TOKEN`.  
Прокси: `TELEGRAM_PROXY=socks5h://127.0.0.1:1080` (если Telegram недоступен напрямую).

**Обновление кода и перезапуск:** после `git pull` остановите текущий процесс бота и запустите `scripts/run_bot.py` снова (или `systemctl restart …`, если бот в systemd). Новый layout модулей (`pipeline/news/`, `pipeline/tech/agents/`, `pipeline/trade/`) подхватывается автоматически; отдельной миграции не нужно.

**CLI без Telegram** (только новостной пайплайн в JSON): [`docs/news_pipeline_cli.md`](news_pipeline_cli.md) — `scripts/run_news_pipeline.py`.

---

## Команды

### `/trade TICKER`

**Краткий итог для входа:** тот же pipeline L0–L6, что и раньше, но ориентир на «торговую выжимку», а не на полный debug.

**Вывод:**
- Только **текст в чате**: Entry/TP/SL (или NO TRADE), компактный L6, импульсы L3–L4, одна строка Fusion, 1–2 строки техники и новостей. **HTML-файл не отправляется** (детали и таблицы — в `/news` и `/signal`).

**Pipeline:**
```
L0-L1  yfinance + Finviz → TickerData, TickerMetrics
L2     LseHeuristicAgent / LlmTechnicalAgent → TechnicalSignal
L3     Yahoo News → FinBERT → DraftImpulse
L4     Gate → LLMMode (SKIP/LITE/FULL); календарь HIGH влияет на FULL
L5     Structured LLM при FULL → AggregatedNewsSignal (при SKIP/LITE вклад News в Fusion = 0)
L6     TradeBuilder → Trade (Entry/TP/SL)
```

### Как принимается окончательное решение (L6)

Сквозная логика L0–L6 своими словами — в разделе **«Поток расчётов: от данных до решения о входе»** выше в этом файле; здесь — только финальный гейт.

Сначала считается **final_bias** — то же число, что строка **Fused** в отчёте:  
`0.55·tech.bias + 0.30·news.bias + 0.15·calendar.broad_equity_bias`. Если новостной агрегат (L5) не строился (gate SKIP), вклад новостей в формуле нулевой.

**TradeBuilder** после этого решает, будет ли позиция LONG, SHORT или **NO TRADE**:

1. **Качество сетапа:** `tradeability_score` с уровня L2 должен быть **не ниже** `MIN_TRADEABILITY_FOR_POSITION` (по умолчанию **0.40**). Иначе вход запрещён: сетап считается слишком слабым, независимо от знака fused.
2. **Направление:** если порог A выполнен, нужно, чтобы **fused** (тот же final_bias) вышел из «мёртвой зоны» около нуля: для **LONG** требуется `fused > MIN_ABS_FINAL_BIAS_FOR_POSITION` (**+0.20**), для **SHORT** — `fused < −0.20`. Если fused между **−0.20** и **+0.20**, сторона не выбирается → **NO TRADE**.

Имена порогов и их значения заданы константами в `pipeline/trade/trade_builder.py` (`MIN_TRADEABILITY_FOR_POSITION`, `MIN_ABS_FINAL_BIAS_FOR_POSITION`). В сообщении `/trade` рядом с LONG / SHORT / NO TRADE приводятся фактические `tradeability` и `fused` (компактный L6).

**NO TRADE** в боте означает: «по правилам L6 вход не предлагается». Это не обязательно то же самое, что иной режим вроде «HOLD» в другом агенте или проекте — там могут быть свои определения.

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

**Новости, геополитика (каналы INC/REG/POL), макро-календарь и тот же L5 (агрегат LLM), что в полном `/signal`** — без техники и без TradeBuilder (без Entry/TP/SL).

Окно заголовков задаётся `NYSE_NEWS_LOOKBACK_NEWS_HOURS` (по умолчанию 48 ч). Гейт L4 и `run_news_signal_pipeline` совпадают по смыслу с `/trade`, но окно статей здесь короче (48 ч / cap 10).

**Вывод:**
- Текст: список `▲/■/▼ канал score заголовок`
- HTML `news_TICKER_...`: календарь, INC/POL, REG, затем секция **«Агрегат новостей (LLM)»** (bias, confidence, summary, таблица per-article при `FULL`) или пояснение при `SKIP`/`LITE`/отсутствии ключа OpenAI

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
  ├── _worker_trade()       → (short_text, пустой html)  ← /trade, только текст в чате
  ├── _worker_signal()      → (short_text, html)   ← /signal и /news_signal, полный debug HTML
  ├── _worker_news()        → (short_text, html)   ← /news, календарь + новости + REG + L5 LLM в HTML
  └── _worker_status()      → str

pipeline/
  ├── debug_runner.py       ← PipelineDebugTrace + run_debug_pipeline()
  ├── html_report.py        ← build_trade_html(), build_news_html(), build_debug_report_html()
  ├── trade/trade_builder.py← TradeBuilder, FusedBias, пороги L6 (корень: trade_builder.py — shim)
  ├── telegram_format.py    ← format_trade(), format_news_list()
  ├── news/gates.py         ← decide_llm_mode() (корень: gates.py — shim)
  ├── news/draft.py         ← draft_impulse() (корень: draft.py — shim)
  ├── news/sentiment.py     ← enrich_cheap_sentiment() (корень: sentiment.py — shim)
  ├── news/news_signal_runner.py ← run_news_signal_pipeline() (корень — shim)
  ├── tech/agents/          ← LseHeuristicAgent, LlmTechnicalAgent (импорт pipeline.technical сохранён)
  └── types.py              ← PROFILE_GAME5M, PROFILE_CONTEXT, ThresholdConfig
```

### Паттерн воркера

Все тяжёлые операции (yfinance, Finviz, FinBERT, LLM) выполняются синхронно
в thread executor, чтобы не блокировать event loop Telegram:

```python
result = await loop.run_in_executor(None, partial(_worker_trade, ticker_str))   # /trade
# или
result = await loop.run_in_executor(None, partial(_worker_signal, ticker_str))  # /signal
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

### `bot/nyse_bot.py` — `_worker_scan`, `_worker_trade` и `_worker_signal`

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

### `pipeline/trade/trade_builder.py` — слияние (1:1 с pystockinvest)

Константы **`W_TECH` / `W_NEWS` / `W_CAL`** (0.55 / 0.30 / 0.15), пороги **`MIN_TRADEABILITY_FOR_POSITION`** / **`MIN_ABS_FINAL_BIAS_FOR_POSITION`**, формула **`_final_confidence`**, вход **LIMIT/MARKET**, **TP/SL** через ATR и `volatility_regime` — как в **`pystockinvest/agent/trade.py`**.  
`KERIM_REPLACE`: в будущем веса можно сделать обучаемыми в агенте Керима; до тех пор не менять без синхронизации с pystockinvest.

### `TechnicalAgentProtocol`

Формальный контракт агента — `pipeline/tech/agents/protocol.py` (импорт `pipeline.technical` — shim):

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
Замена прозрачна для `TradeBuilder` и воркеров `_worker_trade` / `_worker_signal`.

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
