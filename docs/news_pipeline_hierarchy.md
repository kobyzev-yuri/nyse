# Иерархия обработки новостей: §5.4 + pystockinvest + BERT/FinBERT + гибрид с порогами

Цель: совместить **типизацию канала воздействия** (`NewsImpactChannel` из §5.4 `news_calendar_inventory.md`), **полноту structured-сигнала** как в **pystockinvest** `NewsSignalAgent` (sentiment, impact, relevance, horizon, confidence), **дешёвый сентимент как в lse** (FinBERT / transformers pipeline), и **экономию токенов** через пороги и кэш.

Ниже — **слои сверху вниз** (данные идут вниз по конвейеру; «дорогой» слой вызывается только при необходимости).

---

## Уровень 0 — Сбор и нормализация ✅ реализован

- Источники: Yahoo, Marketaux, NewsAPI, Alpha Vantage, RSS → `NewsArticle[]` (расширенный).
- Поля: `published_at`, `url`, `title`, `summary`, `provider_id`, `raw_sentiment` (опционально).

*Кэш:* сырой HTTP / список по тикеру (короткий TTL) — см. `news_cache_and_impulse.md`.

---

## Уровень 1 — Канал воздействия (`NewsImpactChannel`) ✅ реализован

**Задача:** до любого ML/LLM понять, *какого рода* новость это для рынка.

| Канал | Как назначать (от дешёвого к дорогому) |
|-------|----------------------------------------|
| **`INCREMENTAL`** | По умолчанию; или лёгкий классификатор по ключевым словам / отсутствию триггеров REGIME/POLICY |
| **`REGIME`** | Словари (war, sanctions, embargo, …), гео-списки; при сомнении — поднять на уровень 4 (LLM) только эту статью |
| **`POLICY_RATES`** | Ключевые слова (Fed, FOMC, rate hike, …) + пересечение по времени с **`CalendarEvent`** (HIGH) |

**Выход уровня 1:** каждая статья имеет тег канала (и опционально `confidence_rule` 0…1).

*Здесь токены не нужны.*

---

## Уровень 2 — Дешёвый сентимент (`cheap_sentiment`) ✅ реализован

**Задача:** скаляр [−1, 1] на статью без LLM.

Приоритет:
1. **`raw_sentiment`** с провайдера (Marketaux, Alpha Vantage) → ∈ [−1, 1].
2. **FinBERT** / `SENTIMENT_MODEL` (`pipeline/sentiment.py`) → score по `title + summary`.
3. **`price_pattern_boost`** — floor-сигнал по паттернам типа "jumped 15%" / "sinks 7%": перекрывает слабый FinBERT, если в заголовке явное ценовое движение.

**Выход:** `article.cheap_sentiment: float`.

*Токены: 0. Кэш: `cheap_sentiment|sha256(model+text)` → 86400 с.*

---

## Уровень 3 — `DraftImpulse` ✅ реализован

Взвешенное среднее `cheap_sentiment` с затуханием `w = exp(−ln(2)/half_life × age_hours)`.  
Каналы **не смешиваются**: `draft_bias_incremental`, `regime_stress`, `policy_stress` — три отдельных скаляра.  
Реализовано: `pipeline/draft.py`, скалярный прокси: `single_scalar_draft_bias()`.

*Токены: 0. Кэш: 300 с по `(ticker, window, half_life)`.*

---

## Уровень 4 — Гейт (`LLMMode`) ✅ реализован

Реализован в `pipeline/gates.py::decide_llm_mode()`. Порядок ветвей:

| Условие | Результат |
|---------|-----------|
| `calendar_high_soon` | `FULL` |
| `regime_present` и `regime_confidence ≥ T2` | `FULL` |
| `|draft_bias| ≥ T1 × 2.0` (сильный сигнал) | `FULL` |
| `|draft_bias| < T1` и нет REGIME | `SKIP` |
| `article_count > N` | `LITE` |
| иначе | `LITE` |

**Выход:** `LLMMode` (`SKIP` / `LITE` / `FULL`) + `GateContext` (логируется).

---

## Уровень 5 — LLM / `AggregatedNewsSignal` ✅ реализован

`run_news_signal_pipeline(articles, cfg)` → `AggregatedNewsSignal(bias, confidence, summary, items)`.

- Вызывается только при `LITE` / `FULL`.
- При `LITE`: батч сокращается до топ-N по `|cheap_sentiment|`.
- При `FULL`: все статьи в окне.
- Кэш ответа по `cache_key_llm(messages, model, prompt_version)` → TTL 3600 с.
- Для `REGIME` / `POLICY_RATES` — пока тот же промпт; отдельный короткий промпт — в плане (§6 ниже).

---

## Уровень 6 — Слияние с техническим сигналом 🔲 план

- Вход: `AggregatedNewsSignal` (или `draft_bias` при `SKIP`) + `TechnicalSignal` + `CalendarSignal`.
- Выход: `FusedSignal(bias, confidence, side, entry_hint)`.
- Веса `tech / news / calendar` по аналогии с `TradeBuilder` в pystockinvest.
- При `REGIME` в окне — `regime_overhang` снижает итоговую `confidence` или требует отдельного порога для входа.

---

## Визуальная иерархия (одной строкой)

```
Источники → нормализация
    → [1] NewsImpactChannel (правила/календарь)
    → [2] cheap_sentiment (API + FinBERT как в lse)
    → [3] черновой импульс по каналам
    → [4] пороги → решение: skip | lite LLM | full structured
    → [5] structured LLM (news runner) при необходимости
    → [6] Trade / решение о входе
```

---

## Предобработка вместо тяжёлого LLM-фильтра (selection)

Релевантность «до дорогого LLM» можно **сильно** закрыть **не-LLM** методами: окно времени, дедуп по URL, ключевые слова/entity с API, эмбеддинги, лёгкий классификатор. Тогда **LLM selection** либо **сужается** до пограничных статей, либо **опускается**, а LLM остаётся для **signal** на уже отфильтрованном списке. Детали — обсуждение порогов в тестах (ниже).

---

## Калибровка (G): дефолты порогов и профили

| Параметр | Поле в `ThresholdConfig` | Дефолт (`ThresholdConfig()`) | `PROFILE_GAME5M` | `PROFILE_CONTEXT` |
|----------|---------------------------|------------------------------|-----------------|-------------------|
| **T1** | `t1_abs_draft_bias` | `0.20` | `0.12` | `0.20` |
| **T2** | `t2_regime_confidence` | `0.5` | `0.5` | `0.5` |
| **N** | `max_articles_full_batch` | `15` | `8` | `15` |
| **regime_stress_min** | `regime_stress_min` | `0.05` | `0.05` | `0.05` |

`PROFILE_GAME5M` — для волатильных тикеров (SNDK, NBIS, MU, LITE, CIEN, ASML): ниже T1, меньше батч.  
`PROFILE_CONTEXT` — для широких имён (MSFT, META, AMZN, NVDA): стандартные пороги.

Процедура подстройки, метрики «лишние full» и «пропуски», шаблон журнала — **`docs/calibration.md`** (4 прогона зафиксированы). После калибровки обновляйте дефолты в коде (и при необходимости таблицу здесь).

---

## Тесты: калибровка порогов и отладка пайплайна

**Цель тестов на первом этапе:** не только регрессия кода, но и **измеримая база** для **T1, T2, N**, полуокна затухания чернового импульса и словарей каналов.

| Что меряем | Как |
|------------|-----|
| Пороги гейта (уровень 4) | Параметризованные тесты: при заданных `draft_bias`, флаге REGIME, `calendar_high_soon` ожидается `LLMMode` (skip / lite / full). |
| Классификация канала | Фикстуры заголовков (геополитика, FOMC, обычный earnings) → ожидаемый `NewsImpactChannel`. |
| Черновой импульс | Известные времена и sentiment → ожидаемый знак/величина `draft_bias` (с допуском). |
| Кэш | TTL: запись → чтение до истечения OK; после — промах. |
| Регрессия | Зафиксированные JSON-фикстуры статей в `tests/fixtures/` (по мере появления). |

**Единая точка входа для тестов:** `tests/conftest.py` — общие фикстуры (`tmp_cache_dir`, конфиг порогов, примеры статей, `PYTHONPATH` на корень репозитория задаётся через `pytest` из корня `nyse`). Модули тестов лежат в `tests/unit/` и импортируют только публичный API `pipeline.*` и при необходимости `domain`.

**Среда:** запускать тесты в **conda env `py11`** (см. `docs/testing_telegram_plan.md` и `scripts/run_tests.sh`).

**Следующий шаг после кода:** прогон с **реальными** короткими выборками новостей (ручная разметка «ожидали skip vs full») и подстройка порогов по метрикам (доля лишних full-вызовов, доля пропущенных важных — по согласованным критериям).

---

## Согласованность с документами

- §5.4–5.5 `news_calendar_inventory.md` — оси каналов и веса **REGIME**/календаря.
- `news_cache_and_impulse.md` — TTL кэша и реализованные методы импульса.
- `testing_telegram_plan.md` — mock LLM для уровней 4–5 в тестах.
- `calibration.md` — калибровка T1/T2/N (этап G).
- `news_sources_testing_and_pipeline_roadmap.md` — **что покрыто тестами источников** и **текущая дорожная карта** этапов A–G (закрывается по мере выполнения).

---

## Код (пакет `pipeline/`)

Реализация уровней 1, 3, 4 (без LLM) и файлового кэша — в **`pipeline/`**; импорт из корня репозитория: `from pipeline import ...` при `PYTHONPATH=<корень nyse>` или после `pip install -e .` (пакет добавлен в `pyproject.toml`).

*Иерархия и пороги — живой документ; после калибровки обновлять таблицы T1/T2 и примеры.*
