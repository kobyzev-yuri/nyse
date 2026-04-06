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
# dev включает pytest, yfinance, pandas — нужны для integration и sources
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
