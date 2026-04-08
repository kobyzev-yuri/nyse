# Тестирование и Telegram-отладка

Тесты (пирамида) — **реализованы**. Telegram debug-бот — **следующий этап**.

---

## 1. Тесты: текущее состояние

### Окружение: conda `py11`

```bash
conda activate py11
cd /path/to/nyse
pytest tests/ -q
# или без активации:
conda run -n py11 python -m pytest tests/ -q
```

Обёртка: `scripts/run_tests.sh`.  
Конфигурация: `docs/configuration.md`; LLM-ключи — `config_loader.py` / `config.env`.

### Что реализовано

| Уровень | Что покрыто | Кол-во |
|---------|------------|--------|
| Unit | `sources`, `domain`, `pipeline/gates`, `pipeline/sentiment`, `pipeline/draft`, `pipeline/channels`, `pipeline/cache`, `pipeline/types` | 140+ тестов |
| Integration | `sources/news_*` с реальными API (`pytest.mark.integration`); `pipeline` end-to-end с mock LLM | ~20 тестов |
| Calibration | `scripts/calibrate_gate.py` — offline-прогон на реальных данных | ручной запуск |

Журнал калибровки (4 прогона): `docs/calibration.md`.

### Запуск интеграционных тестов

```bash
# Только unit (без сети, без LLM):
pytest tests/unit/ -q

# С интеграционными (нужны ключи в config.env):
pytest tests/ -q -m "not slow"

# Все, включая медленные:
pytest tests/ -q
```

### Fixtures

| Файл | Назначение |
|------|-----------|
| `tests/fixtures/yahoo_news_sample.json` | Сырой ответ Yahoo |
| `tests/fixtures/aggregated_news_signal_expected.json` | Golden-файл для регрессии bias/confidence |
| `tests/conftest.py` | `load_nyse_config`, `mock_llm`, `fake_articles` |

---

## 2. Telegram debug-бот: план (не реализован)

### Зачем

Живая отладка пайплайна без написания скрипта: `/news AAPL` → видишь заголовки + bias + решение гейта. Аналог `cmd/telegram_bot.py` в pystockinvest.

### Команды (минимум)

| Команда | Действие |
|---------|----------|
| `/news <TICKER>` | `sources.NewsSource → enrich_cheap_sentiment → DraftImpulse → decide_llm_mode`; ответ: число статей, bias, режим (SKIP/LITE/FULL), 2–3 заголовка |
| `/signal <TICKER>` | Полный пайплайн уровней 1–5 → `AggregatedNewsSignal`: bias, confidence, summary |
| `/articles <TICKER>` | Только сырые заголовки без LLM (проверка источников) |
| `/gate <TICKER>` | Показать `GateContext` — draft_bias, regime_stress, article_count, calendar_high_soon |

### Реализация

```
nyse/
  cmd/
    telegram_debug_bot.py    ← новый файл
```

Зависимость: `python-telegram-bot>=20` (добавить в `pyproject.toml [project.optional-dependencies] telegram`).  
Токен: `TELEGRAM_BOT_TOKEN` в `config.env`.  
Безопасность: `ALLOWED_CHAT_IDS` — whitelist, те же паттерны что в pystockinvest-боте.

Если LLM-ключа нет — отвечать только данными уровней 1–4 (без LLM-summary).

### Порядок реализации

1. Создать `cmd/telegram_debug_bot.py` с обработчиком `/news`.
2. Добавить зависимость в `pyproject.toml`.
3. Проверить `/articles` — самый простой path (no LLM, no gate).
4. Добавить `/gate` — вывод `GateContext` plain text.
5. Добавить `/signal` — полный пайплайн.
6. Unit-тест для форматтера вывода (текстовый рендер `AggregatedNewsSignal`).
