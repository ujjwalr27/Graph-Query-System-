"""
Semantic search module.
Uses TF-IDF vectorization + cosine similarity over graph node text descriptions.
No model downloads required — works offline with scikit-learn.

To upgrade to neural embeddings, replace _build_index() with a sentence-transformer
or fastembed model; the search interface remains identical.
"""

import logging
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from graph_builder import get_graph_json

logger = logging.getLogger(__name__)

_vectorizer: TfidfVectorizer | None = None
_matrix = None          # sparse TF-IDF matrix (n_nodes × vocab)
_node_ids: list[str] = []
_node_meta: list[dict] = []


def _node_to_text(node: dict) -> str:
    """
    Convert a graph node dict to a rich text string for embedding.
    Includes type, label, id and all metadata fields.
    """
    parts = []
    if node.get("type"):
        parts.append(node["type"].replace("_", " "))
    if node.get("label") and node["label"] != node.get("id"):
        parts.append(str(node["label"]))
    if node.get("id"):
        parts.append(str(node["id"]))

    meta = node.get("metadata") or {}
    for k, v in meta.items():
        if v is not None and str(v).strip():
            # Include key name as context (e.g. "soldtoparty 320000083")
            parts.append(k.replace("_", " "))
            parts.append(str(v))

    return " ".join(parts)


def build_search_index() -> None:
    """
    Build the TF-IDF index over all graph nodes. Called once at startup.
    """
    global _vectorizer, _matrix, _node_ids, _node_meta

    try:
        graph_data = get_graph_json(max_nodes=5000, max_edges=0)
        nodes = graph_data.get("nodes", [])

        if not nodes:
            logger.warning("No nodes found to index for search.")
            return

        _node_ids = [n["id"] for n in nodes]
        _node_meta = nodes

        texts = [_node_to_text(n) for n in nodes]

        _vectorizer = TfidfVectorizer(
            analyzer="word",
            ngram_range=(1, 2),   # unigrams + bigrams
            min_df=1,
            max_features=20_000,
            sublinear_tf=True,    # log normalization
        )
        _matrix = _vectorizer.fit_transform(texts)

        logger.info("Search index built: %d nodes, vocab=%d", len(nodes), len(_vectorizer.vocabulary_))

    except Exception as e:
        logger.error("Failed to build search index: %s", e)


def search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """
    Search the index with a natural language query.
    Returns top-k nodes sorted by relevance score.
    """
    if _vectorizer is None or _matrix is None:
        return []

    try:
        query_vec = _vectorizer.transform([query])
        scores = cosine_similarity(query_vec, _matrix).flatten()
        top_indices = np.argsort(scores)[::-1][:limit]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score < 0.01:
                break  # skip zero-relevance results
            node = _node_meta[idx]
            results.append({
                "id": node["id"],
                "type": node.get("type", ""),
                "label": node.get("label", node["id"]),
                "score": round(score, 4),
            })

        return results

    except Exception as e:
        logger.error("Search error: %s", e)
        return []
