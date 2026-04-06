# План тестов и Telegram-отладки (новости — приоритет, техника — заглушка)

Цель: **отладка новостного контура** и будущих адаптеров **nyse** без обязательной доводки технического входа до уровня ML у Kerima. Технический импульс — **заглушка или упрощённая эвристика**, но **форматы ввода/вывода** совместимы с **pystockinvest** (`domain.Data`, `NewsAgent`, `Orchestrator`, `Trade`), чтобы позже подменить только реализации.

### Окружение: conda `py11`

Тесты и разработка ориентированы на **conda-окружение `py11`** (Python 3.11).

```bash
conda activate py11
cd /path/to/nyse
pip install -e ".[dev]"
python -m pytest tests/
```

Без активации:

```bash
conda run -n py11 python -m pytest tests/ -q
```

В репозитории есть скрипт **`scripts/run_tests.sh`** (обёртка над `conda run -n py11`).

Секреты LLM (ProxyAPI, те же ключи что в `lse/config.env`): см. **`docs/configuration.md`** и **`config_loader.py`**. В юнит-тестах конфиг не подгружается; для интеграции с LLM — фикстура `load_nyse_config` в `tests/conftest.py`.

---

## 1. Роли и границы

| Компонент | nyse (сейчас) | Kerima / pystockinvest (позже) |
|-----------|----------------|----------------------------------|
| Источники данных | `sources/*`, `domain` | Тот же контракт или merge репозитория |
| Новостной агент | отладка, тесты, возможно копия `agent/news/*` при submodule | LLM selection + signal, финальные веса |
| Технический агент | **не цель отладки** — stub | ML / LLM `TechnicalAgent` |
| Слияние в сделку | опционально через `TradeBuilder` или упрощённый вывод | полный `Orchestrator` |

---

## 2. Архитектурное выравнивание с Kerima

Сохранять **те же сигнатуры**, что в pystockinvest:

- **Вход новостей:** `List[domain.NewsArticle]` (поля как в общем `domain` — при расширении nyse добавить optional `source`, позже `impact_channel`).
- **Выход новостного агента:** `Optional[AggregatedNewsSignal]` — `bias`, `confidence`, `summary`, `items` (`NewsSignal` с sentiment, impact, relevance, surprise, time_horizon, confidence).
- **Техника:** `TechnicalAgent.predict(ticker, ticker_data, metrics) -> TechnicalSignal` — для stub возвращать **фиксированный** или **правило по метрикам** объект `TechnicalSignal` с теми же полями, что ожидает `TradeBuilder` (хотя бы `bias`, `confidence`, `tradeability_score`, `breakout_score`, … — см. `agent/models.py` в pystockinvest).

Практика: либо **git submodule / pip dependency** на `pystockinvest` как пакет `agent` + `domain`, либо **тонкий слой** в nyse: `from agent.news.agent import Agent as NewsAgent` при совпадении `PYTHONPATH`. На этапе отладки допустимо **дублировать только DTO** в `nyse/tests/fixtures/` из JSON, не весь репозиторий.

---

## 3. Пирамида тестов

### 3.1. Юнит-тесты (без сети, без LLM)

- **`sources/news.py`**, нормализаторы: фикстуры JSON «как ответ Yahoo» → список `NewsArticle`.
- **`ecalendar`**: замокать `requests` / записать `vcr`-подобные ответы в `tests/fixtures/http/`.
- **`symbols`**: `yfinance_symbol` / `finviz_symbol` / `tickers_from_environ`.
- **Кэш** (когда появится): ключ, TTL, повторный запрос без HTTP.

Запуск: `pytest -q` из корня nyse.

### 3.2. Интеграционные тесты новостей (фокус)

- Поднять **реальный LLM** только в CI/manual с `MARK_*` env; иначе **mock** `BaseChatModel.invoke` → фиксированный JSON, соответствующий `NewsSelectionResponse` / `NewsSignalResponse`.
- Сценарии:
  - пустой список статей → `None` или нейтральный агрегат;
  - 3 статьи → проверка **порядка индексов** и **агрегированного bias** (детерминированный mock).
- **Golden-файлы:** сериализованный `AggregatedNewsSignal` (или только `bias` + `confidence` + хеш списка заголовков) для регрессии при смене промптов у Kerima.

### 3.3. Технический stub (не отлаживаем глубоко)

Варианты (один выбрать как MVP):

1. **`StaticTechnicalAgent`:** всегда `bias=0.1`, `confidence=0.5`, `tradeability_score=0.8`, остальные поля — нейтральные константы из `TechnicalSignal`.
2. **`HeuristicTechnicalAgent`:** простые правила по `TickerMetrics` из nyse (например RSI, отклонение от SMA) → маппинг в `bias` и `confidence` без LLM — «наш след» в коде, но **не цель точности**.

Подключение: тот же `Orchestrator(technical_stub, news_agent, calendar_stub_or_real)`.

### 3.4. Календарь на тестах

- Либо **реальный** малый запрос к Investing (маркер `slow`), либо **фикстура** списка `CalendarEvent` для `CalendarAgent` / заглушки `CalendarSignal` константой.

---

## 4. Структура каталогов (предложение)

```
nyse/
  tests/
    __init__.py
    conftest.py              # pytest fixtures: tickers, mock_llm, paths
    unit/
      test_symbols.py
      test_news_parse.py
      test_ecalendar_mocked.py
    integration/
      test_news_agent_mocked_llm.py
      test_orchestrator_stub_tech.py
    fixtures/
      yahoo_news_sample.json
      aggregated_news_signal_expected.json
  scripts/
    run_news_debug.py        # CLI: один тикер, печать статей + агрегат (без TG)
```

`pyproject.toml`: `[project.optional-dependencies] dev = ["pytest", "pytest-asyncio", "httpx", "respx" или "responses"]`.

---

## 5. Простой Telegram-интерфейс (отладка)

Идея как у Kerima (`cmd/telegram_bot.py` + `ui/telegram`): **python-telegram-bot** v20, **whitelist чатов** (`ALLOWED_CHAT_IDS`), токен из env.

### 5.1. Команды (минимум)

| Команда | Действие |
|---------|----------|
| `/news <TICKER>` | Собрать новости через `sources.NewsSource`, прогнать **только** `NewsAgent` (или цепочку selection+signal), ответить **текстом**: число статей, **bias**, **confidence**, 2–3 строки `summary`, при желании первые N заголовков. |
| `/tech <TICKER>` | Собрать `Data`, вывести **только** результат **технического stub** (для проверки проводки данных; не для «качества» сигнала). |
| `/fuse <TICKER>` или `/signal` | Полный `Orchestrator` + `TradeBuilder`: как `/predict` у Kerima, но короткий текст: `final_bias`, сторона, новостной вклад. |

Опционально: `/articles <TICKER>` — только сырой список заголовков (без LLM) для проверки источников.

### 5.2. Безопасность

- Тот же паттерн: `if chat_id not in allowed: return`.
- Токен только `TELEGRAM_BOT_TOKEN` в `.env`, не в репозитории.

### 5.3. Реализация

- Отдельный модуль `nyse/cmd/telegram_debug_bot.py` или `nyse/ui/telegram_debug.py`, зависимость `python-telegram-bot>=20`.
- Зависимость от **LLM** и **agent** — опционально: если нет ключа, отвечать «новости: только список из Yahoo» без агрегата.

---

## 6. Порядок внедрения

1. Зафиксировать **зависимость от интерфейсов** pystockinvest (документ + пример импорта в README или в этом файле).
2. Добавить **`tests/unit`** для `sources` и парсинга.
3. Добавить **`tests/integration`** с mock LLM для новостного агента (копия тестовых dto из Kerima).
4. Реализовать **`StaticTechnicalAgent`** и один e2e-тест `Orchestrator` → `Trade`.
5. Добавить **`run_news_debug.py`** для локальной отладки без Telegram.
6. Добавить **Telegram debug bot** с `/news` и `/fuse`.

---

## 7. Связь с документом по новостям и режимам

Когда появится поле **`NewsImpactChannel`** (§5.4 `news_calendar_inventory.md`), в тестах добавить кейсы: смесь INCREMENTAL + REGIME → ожидаемое поведение агрегатора (пока зафиксированное в коде nyse, до merge с Kerima).

---

*Документ — план; конкретные имена файлов можно сузить после первого PR с `pytest`.*
