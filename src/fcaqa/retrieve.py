"""Retrieval: find the provisions most likely to answer a question.

Three modes, so the evaluation can compare them:
- keyword: Postgres full-text search. Good at exact terms and rule numbers.
- vector:  nearest neighbours by embedding. Good at paraphrases.
- hybrid:  both, merged with reciprocal rank fusion (RRF).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import psycopg

from .db import vector_literal
from .embed import Embedder

MODES = ("keyword", "vector", "hybrid")
_COLUMNS = "provision_id, sourcebook, provision_type, title, body, url"


@dataclass
class SearchHit:
    provision_id: str
    sourcebook: str
    provision_type: str | None
    title: str
    body: str
    url: str | None
    score: float
    similarity: float | None = None  # cosine similarity, when the vector search saw this hit


def _hit(row: dict, similarity: float | None = None) -> SearchHit:
    return SearchHit(
        provision_id=row["provision_id"], sourcebook=row["sourcebook"],
        provision_type=row["provision_type"], title=row["title"] or "", body=row["body"],
        url=row["url"], score=float(row["score"]), similarity=similarity,
    )


def keyword_search(conn: psycopg.Connection, question: str, k: int, sourcebook: str | None = None) -> list[SearchHit]:
    """Full-text search. Words are OR-ed together, then ranked, because a natural
    question rarely contains every word of the rule that answers it."""
    rows = conn.execute(
        f"""
        WITH q AS (
            SELECT to_tsquery('english',
                   NULLIF(replace(plainto_tsquery('english', %(q)s)::text, '&', '|'), '')) AS tsq
        )
        SELECT {_COLUMNS}, ts_rank_cd(search_tsv, q.tsq) AS score
        FROM provisions, q
        WHERE is_current AND search_tsv @@ q.tsq
          AND (%(book)s::text IS NULL OR sourcebook = %(book)s)
        ORDER BY score DESC, provision_id
        LIMIT %(k)s
        """,
        {"q": question, "k": k, "book": sourcebook.upper() if sourcebook else None},
    ).fetchall()
    return [_hit(row) for row in rows]


def vector_search(
    conn: psycopg.Connection, query_vector: Sequence[float], k: int, sourcebook: str | None = None
) -> list[SearchHit]:
    """Nearest provisions by cosine distance (the <=> operator comes from pgvector)."""
    rows = conn.execute(
        f"""
        SELECT {_COLUMNS}, 1 - (embedding <=> %(v)s::vector) AS score
        FROM provisions
        WHERE is_current AND embedding IS NOT NULL
          AND (%(book)s::text IS NULL OR sourcebook = %(book)s)
        ORDER BY embedding <=> %(v)s::vector
        LIMIT %(k)s
        """,
        {"v": vector_literal(query_vector), "k": k, "book": sourcebook.upper() if sourcebook else None},
    ).fetchall()
    return [_hit(row, similarity=float(row["score"])) for row in rows]


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = 60) -> list[tuple[str, float]]:
    """Merge ranked lists of IDs. Each list gives an item 1 / (k + rank); scores add up.

    Rank matters, raw scores do not, so two searches with different score scales
    can be combined fairly.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


def search(
    conn: psycopg.Connection,
    question: str,
    embedder: Embedder,
    mode: str = "hybrid",
    k: int = 5,
    sourcebook: str | None = None,
    candidates: int = 20,
) -> list[SearchHit]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if mode == "keyword":
        return keyword_search(conn, question, k, sourcebook)

    query_vector = embedder.embed([question])[0]
    if mode == "vector":
        return vector_search(conn, query_vector, k, sourcebook)

    keyword_hits = keyword_search(conn, question, candidates, sourcebook)
    vector_hits = vector_search(conn, query_vector, candidates, sourcebook)
    by_id: dict[str, SearchHit] = {hit.provision_id: hit for hit in keyword_hits}
    for hit in vector_hits:  # keep the vector similarity when both searches found it
        by_id[hit.provision_id] = hit
    fused = reciprocal_rank_fusion(
        [[h.provision_id for h in keyword_hits], [h.provision_id for h in vector_hits]]
    )
    results = []
    for provision_id, score in fused[:k]:
        hit = by_id[provision_id]
        hit.score = score
        results.append(hit)
    return results
