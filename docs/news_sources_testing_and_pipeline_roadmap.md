# Тестирование источников и дорожная карта пайплайна

Живой документ: **зафиксировано состояние на момент ведения работ**; пункты «Сделано» закрываются по мере выполнения, раздел «План продвижения» уточняется, но опирается на основной план: `news_pipeline_hierarchy.md`, `news_cache_and_impulse_proposals.md`, `news_calendar_inventory.md`.

---

## 1. Что сделано: тестирование источников

### 1.1 Интеграция (сеть, `pytest.mark.integration`)

| Область | Файл | Содержание |
|--------|------|------------|
| Свечи Yahoo | `tests/integration/test_sources_smoke.py` | Дневные и часовые (`CandlesSource`) |
| Метрики Finviz | то же | `MetricsSource` |
| Earnings Yahoo | то же | `EarningsSource` |
| Макро-календарь Investing JSON | то же | `CalendarSource` (без API-ключа) |
| Новости Yahoo | то же | `sources.news` (yfinance) |
| Конфиг OpenAI / ProxyAPI | `tests/integration/test_openai_config.py` | Наличие ключа и настроек |
| Один HTTP chat completion | `tests/integration/test_openai_chat_smoke.py` | Реальный POST (при сети); иначе `skip` |
| Пайплайн на реальных заголовках | `tests/integration/test_pipeline_on_news.py` | Yahoo → канал → draft → гейт |
| NewsAPI | `tests/integration/test_news_providers_smoke.py` | При наличии `NEWSAPI_KEY` (иначе skip) |
| Marketaux | то же | При наличии `MARKETAUX_API_KEY` (иначе skip) |
| Alpha Vantage NEWS_SENTIMENT | то же | При наличии `ALPHAVANTAGE_KEY` / `ALPHAVANTAGE_API_KEY` (иначе skip) |
| RSS (публичная лента) | то же | BBC World RSS; при пустом окне / сбое — skip |

**Фикстуры** (`tests/conftest.py`): `load_nyse_config`, `require_openai_settings`, `require_newsapi_key`, `require_marketaux_key`, `require_alphavantage_key`.

**Запуск:** из корня репозитория nyse: `python -m pytest tests/ -v` (интеграционные тесты требуют сеть и при необходимости заполненный `config.env`).

### 1.2 Юнит-тесты (без сети)

| Тема | Файлы |
|------|--------|
| Конфиг | `tests/unit/test_config_loader.py` |
| Кэш | `tests/unit/test_cache.py` |
| Каналы (`NewsImpactChannel`) | `tests/unit/test_channels.py` |
| Черновой импульс | `tests/unit/test_draft.py` |
| Гейты LLM | `tests/unit/test_gates.py` |
| Символы тикеров | `tests/unit/test_symbols.py` |
| Парсинг RSS (XML строка) | `tests/unit/test_news_rss_parse.py` |
| `news_shared.symbol_for_provider` | `tests/unit/test_news_shared.py` |
| NewsAPI / Marketaux / Alpha Vantage | `tests/unit/test_news_*_unit.py` (mock `requests`) |
| Слияние / дедуп (уровень 0) | `tests/unit/test_ingest.py` (`merge_news_articles`, `with_normalized_link`) |
| Дешёвый сентимент (уровень 2) | `tests/unit/test_sentiment.py` (`resolve_cheap_sentiment`, `enrich_cheap_sentiment`, кэш; без загрузки FinBERT) |
| Календарь → гейт (этап C) | `tests/unit/test_calendar_context.py` (`calendar_high_soon`, `build_gate_context`) |
| Кэш новостей / draft (этап E) | `tests/unit/test_news_cache.py`; базовый TTL — `tests/unit/test_cache.py` |
| LLM-клиент и кэш completion (этап F) | `tests/unit/test_llm_client.py`, `test_llm_cache.py`, `test_llm_digest.py` (mock HTTP / без сети) |
| DTO уровня 5 (`NewsSignal`, `AggregatedNewsSignal`) | `tests/unit/test_domain_news_signal.py` (значения enum как в pystockinvest `agent/models.py`) |
| JSON → Pydantic ответ LLM (шаг 2) | `tests/unit/test_news_signal_schema.py` (`parse_news_signal_llm_json`, fence) |
| План батча по `LLMMode` (шаг 3) | `tests/unit/test_llm_batch_plan.py` (`plan_llm_article_batch`) |
| Агрегатор `NewsSignal → AggregatedNewsSignal` (шаг 5) | `tests/unit/test_news_signal_aggregator.py` (веса pystockinvest, 10 тестов) |
| Промпт `build_signal_messages` (шаг 6) | `tests/unit/test_news_signal_prompt.py` (структура, payload JSON, 10 тестов) |
| Оркестратор `run_news_signal_pipeline` (шаг 7) | `tests/unit/test_news_signal_runner.py` (mock HTTP, кэш, 7 тестов); `tests/integration/test_news_signal_runner_smoke.py` (реальный API, skip без сети) |
| Калибровка порогов (G) | Журнал 4 прогонов — `docs/calibration.md`; профили `PROFILE_GAME5M`/`PROFILE_CONTEXT` в `pipeline/types.py`; скрипт `scripts/calibrate_gate.py` |

### 1.3 Реализованные адаптеры новостей (под тесты выше)

- `sources/news.py` — Yahoo (yfinance), `provider_id=yfinance`
- `sources/news_newsapi.py` — NewsAPI v2
- `sources/news_marketaux.py` — Marketaux v1
- `sources/news_alphavantage.py` — Alpha Vantage `NEWS_SENTIMENT`
- `sources/news_rss.py` — RSS/Atom → `NewsArticle`
- `config_loader`: `get_newsapi_key`, `get_marketaux_api_key`, `get_alphavantage_api_key` (и совместимость с `ALPHAVANTAGE_API_KEY`)

**Домен:** `NewsArticle` с опциональными `provider_id`, `raw_sentiment`, **`cheap_sentiment`** (уровень 2); тикер `Ticker.GENERAL` для нетикерных лент.

**Пайплайн:** `pipeline/sentiment.py` — приоритет `raw_sentiment` → иначе HuggingFace (`SENTIMENT_MODEL`, опционально `pip install -e ".[sentiment]"`), кэш `FileCache` при передаче в `resolve_cheap_sentiment` / `enrich_with_default_cache`; env: `NYSE_SENTIMENT_LOCAL`, `NYSE_SENTIMENT_CACHE_TTL_SEC`.

**Календарь и гейт:** `pipeline/calendar_context.py` — `calendar_high_soon(events, now=..., minutes_before/after=...)` и `build_gate_context(..., calendar_events=...)`; окно HIGH по умолчанию из `NYSE_CALENDAR_HIGH_BEFORE_MIN` / `NYSE_CALENDAR_HIGH_AFTER_MIN`.

**Черновой импульс (этап D):** `DraftImpulse` дополнен счётчиками статей и суммами весов по каналам, `max_abs_regime` / `max_abs_policy`; среднее по INCREMENTAL по-прежнему не смешивается с REGIME/POLICY (`draft_impulse`).

**Кэш (этап E):** `pipeline/news_cache.py` — JSON-сериализация статей, `get_or_set_articles` / `get_or_set_draft_impulse`, `default_news_file_cache()`; корень по умолчанию ``<корень nyse>/.cache/nyse``.

**LLM (этап F):** `pipeline/llm_client.py`, `llm_cache.py`, `llm_digest.py` — completion по `get_openai_settings()`, кэш ответа по `cache_key_llm(...)`; TTL `NYSE_LLM_CACHE_TTL_SEC` (см. `config_loader.llm_cache_ttl_sec`).

**К уровню 5 (шаги 2–4):** `pipeline/news_signal_schema.py` — Pydantic `NewsSignalLLMResponse`, `parse_news_signal_llm_json`; `pipeline/llm_batch_plan.py` — `plan_llm_article_batch` / `LlmArticlePlan`; зависимость **`pydantic>=2`** в `pyproject.toml`.

**Калибровка (G):** `docs/calibration.md` — журнал 4 прогонов, профили GAME5M/CONTEXT, `price_pattern_boost` в `pipeline/sentiment.py`.

**Пакет `sources`:** ленивые импорты в `sources/__init__.py`, чтобы подключение календаря не требовало yfinance.

### 1.4 Намеренно не автоматизировано в CI без договорённости

- Полный structured LLM-пайплайн на прод-промптах; для HTTP completion есть mock в `tests/unit/test_llm_*.py` (см. `docs/testing_telegram_plan.md`).
- Минутные свечи (тяжёлый/лимитный запрос к Yahoo).
- Скрейп Investing HTML-ленты (хрупко; в nyse приоритет API/RSS).

---

## 2. План продвижения по основному плану (следующие этапы)

Опора на уровни `news_pipeline_hierarchy.md`: после сбора идут нормализация → канал → дешёвый сентимент → черновой импульс → пороги → LLM → слияние с техникой/календарём.

### 2.1 Этапы A–G — закрыты в коде и тестах (снимок)

Ниже — **зафиксированный** объём буквенных этапов; детали реализации и файлы см. §1.

| # | Этап | Содержание | Критерий «готово» |
|---|------|------------|-------------------|
| **A** | Слияние и фильтр уровня 0 | **`pipeline.merge_news_articles`**, **`pipeline.with_normalized_link`** (`pipeline/ingest.py`): несколько итерируемых наборов → дедуп по каноническому URL или составному ключу без ссылки, окно `lookback_hours`, сортировка по времени | `tests/unit/test_ingest.py` |
| **B** | Уровень 2: сентимент | **`pipeline.resolve_cheap_sentiment`**, **`enrich_cheap_sentiment`**, **`enrich_with_default_cache`** (`pipeline/sentiment.py`): приоритет API `raw_sentiment` → иначе FinBERT/`SENTIMENT_MODEL`; кэш по ключу hash(модель+текст) | `tests/unit/test_sentiment.py`; зависимость опционально: `pip install -e ".[sentiment]"` |
| **C** | Календарь в гейте | **`pipeline.calendar_high_soon`**, **`build_gate_context`** (`pipeline/calendar_context.py`): только `HIGH`, окно `[now−after, now+before]` мин (env `NYSE_CALENDAR_HIGH_*`) | `tests/unit/test_calendar_context.py`; живые события — по-прежнему `sources.ecalendar` → список `CalendarEvent` |
| **D** | Уровень 3 (уточнение) | **`DraftImpulse`**: счётчики статей и суммы весов по каналам; ``max_abs_regime`` / ``max_abs_policy``; среднее INCREMENTAL отделено от REGIME/POLICY (`pipeline/types.py`, `draft_impulse`) | `tests/unit/test_draft.py` (в т.ч. «только REGIME» не даёт ненулевой incremental) |
| **E** | Кэш по доку | **`pipeline/news_cache.py`**: сериализация ``NewsArticle``, ``get_or_set_articles`` / ``get_or_set_draft_impulse``, ключи ``cache_key_*``; env ``NYSE_CACHE_ROOT``, ``NYSE_NEWS_RAW_TTL_SEC``, ``NYSE_NEWS_AGGREGATE_TTL_SEC`` | `tests/unit/test_news_cache.py` + базовый `test_cache.py` |
| **F** | HTTP LLM + кэш completion + lite-дайджест | **`pipeline/llm_client.py`**, **`llm_cache.py`**, **`llm_digest.py`** (см. §1.3); инфраструктура вызова и кэша до полного news-runner | `tests/unit/test_llm_*.py` |
| **G** | Калибровка порогов | Процедура и журнал T1/T2/N; подстройка по живым выборкам — **непрерывный** процесс | **`docs/calibration.md`**, таблица в **`news_pipeline_hierarchy.md`** (§ «Калибровка (G)») |

**Порядок работ (исторический):** A → B → C параллельно с уточнением D; E по мере нагрузки на API; F после стабилизации 1–4 уровней; **G идёт параллельно с эксплуатацией**, не «одним коммитом».

### 2.2 После F: что дальше (вне букв A–G)

Буквы **A–G** закрывают **базовый контур nyse** (источники → гейт → тонкий LLM). Дальше по `news_pipeline_hierarchy.md`:

| Уровень / тема | Содержание | Примечание |
|----------------|------------|------------|
| **G (ongoing)** | Калибровка `ThresholdConfig`, журнал в `calibration.md` | 4 прогона; профили GAME5M/CONTEXT; баг fix в порядке гейта; `price_pattern_boost` |
| **Уровень 5** | Полный **structured LLM** (как pystockinvest): selection при необходимости, `NewsSignal` / `AggregatedNewsSignal`, промпты и контракт совпадают | Сверх F: не только `chat_completion_text`, а согласованные DTO и агрегация |
| **Уровень 6** | Слияние **техника + новости + календарь** в `Trade` | ✅ Реализовано: `pipeline/trade_builder.py` = логика `pystockinvest/agent/trade.py` |
| **Интеграция / CI** | Опционально: один **smoke**-integration тест с реальным HTTP completion (ключ в env, маркер `integration`) | Сейчас `test_openai_config.py` проверяет только загрузку настроек, не вызов API |

При появлении устойчивого следующего чеклиста (уровни 5–6 + агент) имеет смысл **заархивировать** этот файл по правилам §3 и вести новый документ под оркестратор/прод.

---

## 3. Как закрывать этот документ

- Раздел **§1** при смене набора тестов/адаптеров — обновлять фактами (даты по желанию в коммите).
- Раздел **§2.1** — таблица A–G остаётся как **исторический снимок**; новые буквенные этапы не добавлять без пересмотра всего плана.
- Раздел **§2.2** — дополнять по мере появления задач уровней 5–6 (или вынести в отдельный чеклист).
- Когда основная работа сместится на **уровни 5–6 и агент**, этот документ можно **заархивировать** (переименовать в `*_archive_YYYY-MM.md`) и вести следующий чеклист под оркестратор/прод.

---

## 4. Связанные документы

- `news_pipeline_hierarchy.md` — иерархия уровней и идея тестов порогов.
- `calibration.md` — процедура калибровки T1/T2/N (этап G).
- `news_cache_and_impulse_proposals.md` — кэш, окна, импульс.
- `news_calendar_inventory.md` — провайдеры, типизация, пробелы.
- `docs/testing_telegram_plan.md` / `scripts/run_tests.sh` — среда `py11`, запуск pytest.
