# Конфигурация nyse (секреты, ProxyAPI, тесты)

## Файлы

| Файл | Назначение |
|------|------------|
| **`config.env.example`** | Шаблон переменных; коммитится в git. |
| **`config.env`** | Локальные секреты; **не коммитится** (`.gitignore`). |

## LLM / ProxyAPI (как в lse)

Те же переменные, что в **`lse/config.env`**:

- `OPENAI_API_KEY` — ключ ProxyAPI или OpenAI  
- `OPENAI_BASE_URL` — например `https://api.proxyapi.ru/openai/v1`  
- `OPENAI_MODEL`, `OPENAI_TEMPERATURE`, `OPENAI_TIMEOUT`

Загрузка в коде: **`config_loader.load_config_env()`** затем **`get_openai_settings()`**.

### Варианты без дублирования ключей

1. **Symlink** из каталога nyse:  
   `ln -s /path/to/lse/config.env /path/to/nyse/config.env`
2. **Переменная окружения** (абсолютный путь к любому файлу, в т.ч. lse):  
   `export NYSE_CONFIG_PATH=/path/to/lse/config.env`
3. Если нет ни `config.env` в nyse, ни `NYSE_CONFIG_PATH`, загрузчик **пробует** `../lse/config.env` относительно корня репозитория nyse (удобно при соседних `lse` и `nyse` в одной родительской папке).

Приоритет: уже заданные переменные окружения **не перезаписываются** файлами.

## Structured LLM и экономия токенов (расширения относительно pystockinvest)

Архитектура DTO/промптов совпадает с **pystockinvest** (`agent/news`, `agent/market`, `agent/calendar`). В NYSE дополнительно:

| Механизм | Где | Смысл |
|----------|-----|--------|
| **Гейт L4** | `pipeline/gates.py` | Режим `SKIP` не вызывает news-LLM; `LITE` — дайджест без полного structured signal |
| **Кэш completion** | `pipeline/llm_cache.py`, `cache_key_llm` | Одинаковый вход (промпт + модель + `PROMPT_VERSION`) → повтор без API |
| **Версии промптов** | `PROMPT_VERSION` в `*_prompt.py` | Смена текста промпта инвалидирует старый кэш |
| **Календарь chunked** | `calendar_signal_runner.py` | В ключ кэша добавляется индекс батча, чтобы чанки с одинаковым событием не путались |

Переменные: `NYSE_LLM_TECHNICAL`, `NYSE_LLM_CALENDAR`, `NYSE_CALENDAR_LLM_BATCH_SIZE`, `NYSE_LLM_CACHE_TTL_SEC` — см. `config.env.example` и `config_loader.py`.

## Пороги гейта (`ThresholdConfig`)

Базовый профиль для бота — **`PROFILE_GAME5M`** (`pipeline/types.py`). Переопределения без правки кода:

| Переменная | Поле |
|------------|------|
| `NYSE_GATE_T1` | `t1_abs_draft_bias` |
| `NYSE_GATE_T2` | `t2_regime_confidence` |
| `NYSE_GATE_MAX_N` | `max_articles_full_batch` |
| `NYSE_GATE_REGIME_STRESS_MIN` | `regime_stress_min` |

Читает **`config_loader.get_pipeline_gate_threshold()`** (используется в **`bot/nyse_bot.py`**). Подробности — **`docs/calibration.md`**.

## Telegram (бот и smoke-тесты)

| Переменная | Назначение |
|------------|------------|
| `TELEGRAM_BOT_TOKEN` | Токен @BotFather |
| `TELEGRAM_PROXY` | Прокси для `api.telegram.org`, см. `docs/bot.md` |
| `TELEGRAM_SIGNAL_CHAT_ID` или `TELEGRAM_SIGNAL_CHAT_IDS` | Чат для `tests/integration/test_telegram_bot_smoke.py` и сигналов |

## Где конфиг в тестах

- **Юнит-тесты** (`tests/unit/`) **не** читают `config.env` и **не** требуют ключей. Используются только фикстуры из **`tests/conftest.py`**.
- **Интеграционные тесты** с реальным LLM (когда появятся): помечайте `@pytest.mark.integration`, в начале пропускайте, если нет `OPENAI_API_KEY`, или вызывайте опциональную фикстуру **`load_nyse_config`** (см. `conftest.py`).

Так CI и локальные прогоны без секретов остаются зелёными.

## Запуск тестов

**Только юнит-тесты** (без сети и без `config.env`):

```bash
conda activate py11
cd /path/to/nyse
pip install -e ".[dev]"
# Базовые зависимости (yfinance, pandas, requests, pytz, finvizfinance) ставятся через `pip install -e .`
# `[dev]` добавляет только pytest
python -m pytest tests/unit/ -q
```

**Интеграционные** (нужны `config.env` с `OPENAI_API_KEY`, для Yahoo — сеть):

```bash
python -m pytest tests/integration/ -v -m integration
```

**Всё** (юнит + интеграция):

```bash
python -m pytest tests/ -v
```

Или `./scripts/run_tests.sh tests/ -v`.
