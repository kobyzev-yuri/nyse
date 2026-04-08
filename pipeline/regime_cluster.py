"""
Кластеризация статей канала REGIME по смысловой близости (одна гео-тема → один вклад в draft_impulse).

Используется только для расчёта ``scored_from_news_articles`` / ``draft_impulse`` / гейта.
Полный список ``articles`` для LLM и HTML-таблиц не сокращается.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from domain import NewsArticle


@dataclass(frozen=True)
class RegimeClusterMeta:
    """Метаданные прохода кластеризации REG (для отчёта и отладки)."""

    enabled: bool
    embed_backend: str
    n_reg_in: int
    n_reg_out: int
    n_clusters: int
    threshold: float
    note: str


def _article_text(a: "NewsArticle") -> str:
    s = (a.summary or "")[:1500]
    return f"{a.title}\n{s}".strip()


def _tfidf_unit_matrix(texts: List[str]) -> "np.ndarray":
    """Batch TF-IDF, строки L2-нормированы (косинус = скалярное произведение)."""
    import numpy as np

    if not texts:
        return np.zeros((0, 0))
    docs_tokens = [re.findall(r"[a-z0-9]+", t.lower()) for t in texts]
    vocab: dict[str, int] = {}
    for tokens in docs_tokens:
        for tok in set(tokens):
            if tok not in vocab:
                vocab[tok] = len(vocab)
    n_docs = len(texts)
    n_terms = len(vocab)
    if n_terms == 0:
        return np.ones((n_docs, 1), dtype=np.float64) / math.sqrt(max(n_docs, 1))

    x = np.zeros((n_docs, n_terms), dtype=np.float64)
    for i, tokens in enumerate(docs_tokens):
        tf = Counter(tokens)
        for tok, c in tf.items():
            j = vocab.get(tok)
            if j is not None:
                x[i, j] = float(c)
    df = (x > 0).sum(axis=0)
    idf = np.log((1.0 + n_docs) / (1.0 + df)) + 1.0
    x = x * idf
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-9)
    return x / norms


def _embed_openai(texts: List[str], *, api_key: str, base_url: str, model: str, timeout: int) -> List[List[float]]:
    import requests

    url = base_url.rstrip("/") + "/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    out: List[List[float]] = []
    batch = 24
    for i in range(0, len(texts), batch):
        chunk = texts[i : i + batch]
        r = requests.post(
            url,
            headers=headers,
            json={"model": model, "input": chunk},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        embs = sorted(data["data"], key=lambda d: d["index"])
        for e in embs:
            out.append(e["embedding"])
    return out


def _l2_normalize_rows(vectors: List[List[float]]) -> "np.ndarray":
    import numpy as np

    x = np.asarray(vectors, dtype=np.float64)
    if x.size == 0:
        return x.reshape(0, 0)
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-9)
    return x / norms


def _greedy_clusters_from_cosine(
    embeddings: "np.ndarray",
    threshold: float,
    process_order: List[int],
) -> List[List[int]]:
    """
    Жадная кластеризация: перебор в ``process_order`` (обычно свежие REG раньше);
    статья присоединяется к первому кластеру, где max косинус с любым членом >= threshold.
    """
    import numpy as np

    clusters: List[List[int]] = []
    for i in process_order:
        v = embeddings[i]
        placed = False
        for cl in clusters:
            sims = [float(np.dot(v, embeddings[j])) for j in cl]
            if sims and max(sims) >= threshold:
                cl.append(i)
                placed = True
                break
        if not placed:
            clusters.append([i])
    return clusters


def _pick_representative(cluster_row_indices: List[int], articles_reg: List["NewsArticle"]) -> int:
    """Индекс в articles_reg: максимум |cheap_sentiment|, при равенстве — более свежая дата."""
    from datetime import datetime, timezone

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def ts_key(a: "NewsArticle") -> datetime:
        t = a.timestamp
        return t if isinstance(t, datetime) else epoch

    best_local = cluster_row_indices[0]
    best = articles_reg[best_local]
    best_cs = abs(best.cheap_sentiment or 0.0)
    best_ts = ts_key(best)
    for loc in cluster_row_indices[1:]:
        a = articles_reg[loc]
        cs = abs(a.cheap_sentiment or 0.0)
        ts = ts_key(a)
        if cs > best_cs + 1e-9 or (abs(cs - best_cs) < 1e-9 and ts > best_ts):
            best_local = loc
            best_cs = cs
            best_ts = ts
    return best_local


def apply_regime_cluster_for_draft(
    articles: Sequence["NewsArticle"],
    *,
    now,
    enabled: Optional[bool] = None,
    similarity_threshold: Optional[float] = None,
    embed_backend: Optional[str] = None,
    openai_settings=None,
) -> Tuple[List["NewsArticle"], Optional[RegimeClusterMeta]]:
    """
    Возвращает список статей для ``scored_from_news_articles`` / ``draft_impulse``:
    все INC/POL без изменений; REG схлопнут по темам (один представитель на кластер).

    Если ``enabled`` is False или REG < 2 — возвращает исходный список, meta=None.
    """
    from domain import NewsArticle

    import config_loader
    from .channels import classify_channel
    from .types import NewsImpactChannel

    load_cfg = enabled is None or similarity_threshold is None or embed_backend is None
    if load_cfg:
        config_loader.load_config_env()

    if enabled is None:
        raw = (os.environ.get("NYSE_REGIME_CLUSTER") or "1").strip().lower()
        enabled = raw not in ("0", "false", "no", "off")

    if not enabled or len(articles) < 2:
        return list(articles), None

    if similarity_threshold is None:
        similarity_threshold = float(os.environ.get("NYSE_REGIME_CLUSTER_THRESHOLD") or "0.88")

    if embed_backend is None:
        embed_backend = (os.environ.get("NYSE_REGIME_CLUSTER_EMBED") or "tfidf").strip().lower()

    reg_idx: List[int] = []
    non_reg: List[NewsArticle] = []
    for i, a in enumerate(articles):
        if not isinstance(a, NewsArticle):
            raise TypeError("expected NewsArticle")
        ch, _ = classify_channel(a.title, a.summary)
        if ch == NewsImpactChannel.REGIME:
            reg_idx.append(i)
        else:
            non_reg.append(a)

    articles_reg = [articles[i] for i in reg_idx]
    n_reg_in = len(articles_reg)
    if n_reg_in < 2:
        return list(articles), None

    texts = [_article_text(a) for a in articles_reg]

    embed_backend_resolved = embed_backend
    vectors: "np.ndarray"
    try:
        if embed_backend == "openai":
            oai = openai_settings if openai_settings is not None else config_loader.get_openai_settings()
            if not oai:
                embed_backend_resolved = "tfidf"
                vectors = _tfidf_unit_matrix(texts)
            else:
                model = (os.environ.get("NYSE_REGIME_CLUSTER_EMBEDDING_MODEL") or "text-embedding-3-small").strip()
                raw_vecs = _embed_openai(
                    texts,
                    api_key=oai.api_key,
                    base_url=oai.base_url,
                    model=model,
                    timeout=min(oai.timeout_sec, 120),
                )
                vectors = _l2_normalize_rows(raw_vecs)
        else:
            vectors = _tfidf_unit_matrix(texts)
    except Exception:
        embed_backend_resolved = "tfidf"
        vectors = _tfidf_unit_matrix(texts)

    # порядок: сначала более свежие REG (жадность к «якорным» свежим заголовкам)
    process_order = sorted(
        range(n_reg_in),
        key=lambda k: articles_reg[k].timestamp or now,
        reverse=True,
    )
    clusters_rows = _greedy_clusters_from_cosine(vectors, similarity_threshold, process_order)

    reps: List[NewsArticle] = []
    for cl in clusters_rows:
        local_best = _pick_representative(cl, articles_reg)
        reps.append(articles_reg[local_best])

    merged = non_reg + reps
    meta = RegimeClusterMeta(
        enabled=True,
        embed_backend=embed_backend_resolved,
        n_reg_in=n_reg_in,
        n_reg_out=len(reps),
        n_clusters=len(clusters_rows),
        threshold=similarity_threshold,
        note=f"REG: {n_reg_in} статей → {len(reps)} тем ({len(clusters_rows)} кластеров), backend={embed_backend_resolved}",
    )
    return merged, meta


__all__ = [
    "RegimeClusterMeta",
    "apply_regime_cluster_for_draft",
]
