"""HTTP API. Run with:  uvicorn fcaqa.api:app --reload   then open /docs"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .answer import DISCLAIMER, answer_question
from .db import connect
from .embed import Embedder, get_embedder
from .ingest import recent_changes
from .llm import ChatLLM, get_llm
from .parse import normalise_id

app = FastAPI(
    title="FCA Handbook Q&A",
    description=f"Answers with cited provisions, or a refusal. {DISCLAIMER}",
    version="0.1.0",
)


@lru_cache(maxsize=1)
def embedder() -> Embedder:  # loaded once, the model is slow to start
    return get_embedder()


@lru_cache(maxsize=1)
def llm() -> ChatLLM:
    return get_llm()


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    k: int = Field(default=5, ge=1, le=20)
    sourcebook: str | None = None


@app.get("/health")
def health() -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT count(*) FILTER (WHERE is_current) AS provisions, "
            "count(*) FILTER (WHERE is_current AND embedding IS NULL) AS missing_embeddings FROM provisions"
        ).fetchone()
        last = conn.execute("SELECT max(taken_at) AS last_snapshot FROM snapshots").fetchone()
    return {"status": "ok", **row, **last}


@app.post("/ask")
def ask(request: AskRequest) -> dict:
    with connect() as conn:
        answer = answer_question(
            conn, request.question, embedder(), llm(), request.mode, request.k, request.sourcebook
        )
    return answer.to_dict()


@app.get("/provisions/{provision_id}")
def get_provision(provision_id: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT provision_id, sourcebook, chapter, section, provision_type, title, body, url, is_current "
            "FROM provisions WHERE provision_id = %s",
            (normalise_id(provision_id),),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No such provision")
    return row


@app.get("/changes")
def changes(limit: int = 50) -> list[dict]:
    with connect() as conn:
        return recent_changes(conn, min(max(limit, 1), 500))
