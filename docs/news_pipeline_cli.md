## News pipeline CLI (JSON) — как `/news`, но отдельным скриптом

Скрипт `scripts/run_news_pipeline.py` выделяет **только новостной пайплайн** из бота (уровни L3–L5 вокруг `/news`) и печатает результат в **JSON**.

Код новостного конвейера в репозитории: пакет **`pipeline/news/`** (каналы, sentiment, draft, гейт, `news_signal_*`). Старые импорты вида `from pipeline.sentiment import …` по-прежнему работают через shim-файлы в корне `pipeline/`.

### Связанные пакеты (кратко)

| Область | Папка в репо | Примечание |
|---------|--------------|------------|
| Новости L1–L5 | `pipeline/news/` | Реализация; в корне `pipeline/` — тонкие shim-модули с теми же именами. |
| Техника L2 | `pipeline/tech/agents/` | Бывший `pipeline/technical/`; импорт `from pipeline.technical import …` сохранён через `pipeline/technical/__init__.py`. |
| Сделка L6 | `pipeline/trade/trade_builder.py` | `from pipeline.trade_builder import …` — через shim в корне. |

### Что именно делает (соответствует `/news`)

- **Загрузка новостей**: окно по умолчанию 48 часов, лимит 10 статей на тикер (как в `/news`).
- **Cheap sentiment**: `enrich_cheap_sentiment` (API sentiment / FinBERT / price-pattern).
- **DraftImpulse**: расчёт L3 по каналам INC/REG/POL + `single_scalar_draft_bias`.
- **Gate**: `decide_llm_mode` по профилю порогов (по умолчанию `PROFILE_GAME5M`).
- **LLM агрегация (опционально)**: `run_news_signal_pipeline` возвращает `AggregatedNewsSignal` (bias/confidence/summary/items).

### Выход

По умолчанию **stdout = только JSON** (это важно для пайпов).  
Любые сообщения зависимостей (например прогресс FinBERT или предупреждения провайдеров) перенаправляются в **stderr**.

JSON включает:

- **`articles[]`**: заголовок/summary/link/provider_id/published_at_utc, канал (`channel`) + rule-confidence, `cheap_sentiment`, `raw_sentiment`
- **`draft_impulse`** и **`single_scalar_draft_bias`**
- **`gate`**: `llm_mode`, `reason`, `calendar_high_soon`, `regime_present`, и т.д.
- **`aggregated_news_signal`**: появляется только если LLM реально вызывался (см. ниже)

### Примеры

Печать JSON:

```bash
cd /path/to/nyse
conda run -n py11 python scripts/run_news_pipeline.py MU --pretty
```

Сохранение в файл:

```bash
conda run -n py11 python scripts/run_news_pipeline.py MU --pretty --json-out /tmp/mu.json
```

Отключить LLM даже если задан `OPENAI_API_KEY`:

```bash
conda run -n py11 python scripts/run_news_pipeline.py MU --no-llm --pretty
```

Быстро проверить, что LLM реально отработал:

```bash
conda run -n py11 python scripts/run_news_pipeline.py MU --pretty \
  | python -c 'import sys,json; d=json.load(sys.stdin); print(d["gate"]["llm_mode"], bool(d["aggregated_news_signal"]))'
```

### Как включить LLM

Нужен `OPENAI_API_KEY` (обычно через `config.env`, который подхватывается `config_loader.load_config_env()`).

Важно: **structured LLM по новостям вызывается только при `llm_mode=full`**.  
Если гейт вернул `skip`/`lite`, то `run_news_signal_pipeline` вернёт нейтральный результат без structured LLM, и `aggregated_news_signal` будет отсутствовать/пустым (в зависимости от режима запуска).

### Перезапуск Telegram-бота после обновления кода

Да, бот можно перезапустить в любой момент. После `git pull` в корне репозитория `nyse`:

1. Убедитесь, что `config.env` на месте (токен бота, ключи API и т.д.).
2. Остановите текущий процесс бота (systemd, docker, screen/tmux, или `Ctrl+C` в терминале, где запущен `scripts/run_bot.py`).
3. Запустите снова, например:  
   `conda run -n py11 python scripts/run_bot.py`

Если бот крутится как systemd-сервис — используйте `systemctl restart …` для вашего unit-файла. Перезапуск подхватывает новый код с диска; отдельной миграции БД для этого рефакторинга не требуется.

