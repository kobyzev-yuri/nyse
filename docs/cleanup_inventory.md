# Инвентарь очистки: legacy-код и `tests/support`

## 1. Выполнено: низкоуровневый HTTP completion

| Было | Стало |
|------|--------|
| `pipeline/llm_client.py` | `tests/support/openai_chat_completion.py` |
| Ленивый экспорт `pipeline.chat_completion_text` в `pipeline/__init__.py` | Удалён (`__all__` и `__getattr__`) |

Тесты импортируют: `from tests.support import chat_completion_text`.

Продакшен-пайплайн и бот по-прежнему используют `pipeline.llm_factory.get_chat_model()` (LangChain).

Обновлены: `README.md`, `docs/architecture.md`, `docs/calibration.md`, `docs/news_sources_testing_and_pipeline_roadmap.md`; уточнены docstring в `pipeline/llm_digest.py`, `pipeline/news_signal_prompt.py`.

## 2. Схема для следующих переносов

1. Проверить **бот** (`bot/nyse_bot.py`) и **скрипт запуска** (`scripts/run_bot.py`): нет ли прямого или косвенного использования символа.
2. Проверить **`pipeline/__init__.py`**: многие символы отдаются через `__getattr__` — поиск только по `from pipeline.foo import` занижает использование.
3. Перенос вспомогательного кода в **`tests/support/`** (один пакет, импорт `from tests.support import ...`).
4. Удалить реэкспорты из `pipeline`, обновить тесты и доки, прогнать `pytest tests/unit/`.

## 3. Обзор `sources/` (2026-04)

- **Зависимость на pipeline:** `news_merge.fetch_merged_news` вызывает `pipeline.ingest.merge_news_articles` — осознанно: дедуп уровня 0 живёт в `pipeline`, не дублируется в `sources`.
- **Удалён мёртвый код:** `ParsedNewsItem` в `sources/news.py` нигде не использовался — убран.
- **Удалён опечаточный alias:** `get_dayly_candles` в `sources/candles.py` (вызывавший `get_daily_candles`); внешних вызовов не было.

### Обзор `pipeline/` (точки входа бота)

Бот тянет: `html_report`, `sentiment`, `draft`, `regime_cluster`, `telegram_format`, `calendar_context`, `debug_runner`, `calendar_llm_agent`, `technical` (эвристика/LLM). Остальное — раннеры сигналов, `trade_builder`, кэш, гейты, LLM-схемы: используются пайплайном и тестами, не «лишнее». `debug_runner` импортирует `sources.news` / `sources.ecalendar` — нормальная связка отладочного прогона с теми же источниками, что и бот.

## 4. Кандидаты на ручной разбор (не автоматическое удаление)

**Похожие на бывший `llm_client`** (отдельный низкоуровневый слой только ради тестов/совместимости):

- Сейчас отдельного аналога нет: остальной LLM-стек — `llm_factory`, раннеры, `lc_shim`.

**Не путать с «мёртвым» кодом:** `llm_cache`, `news_cache`, `ingest` и др. часто **не** импортируются как `pipeline.llm_cache`, а через `from pipeline import get_or_set_articles` и ленивую загрузку в `__init__.py`.

**Осознанные утилиты в `pipeline/`** (используются другими модулями пайплайна):

- `chunked.py` — батчи списков (`calendar_signal_runner`).
- `lc_shim.py` — обёртка LangChain-сообщений в раннерах.

**Скрипты:**

- `scripts/run_bot.py` — точка входа бота.
- `scripts/calibrate_gate.py` — офлайн-калибровка; не «хлам», а операционная утилита (см. `docs/calibration.md`).

## 5. Инструменты для следующего прохода

- Обратный поиск: кто импортирует модуль (включая `from pipeline import ...`).
- Осторожно: `vulture` / только `F401` — много ложных срабатываний из‑за lazy imports.
- Покрытие: `pytest --cov=pipeline` — файлы с 0% не обязаны быть мёртвыми (могут подгружаться динамически).
