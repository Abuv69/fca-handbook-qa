"""Answering: retrieve, ask the model, then let code decide whether to trust it.

The model reads; code makes the final call. An answer is only returned if it
cites at least one provision that was actually retrieved. Otherwise we refuse.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field

import psycopg

from .config import get_settings
from .embed import Embedder
from .llm import ChatLLM
from .parse import normalise_id
from .retrieve import SearchHit, search

NOT_FOUND = "NOT_FOUND"
REFUSAL_TEXT = "I could not find this in the provisions I have. Try rephrasing, or check the Handbook directly."
DISCLAIMER = "Information only, not legal or regulatory advice. Always check the official Handbook."

SYSTEM_PROMPT = f"""You answer questions about a rulebook using ONLY the sources provided.

Rules:
1. Use only facts stated in the sources. Never use outside knowledge.
2. After each claim, cite the source ID in square brackets, exactly as given, e.g. [CONC 5.2A.4R].
3. If the sources do not contain the answer, reply with exactly: {NOT_FOUND}
4. Be concise: at most five sentences. Do not give advice."""

_CITATION_RE = re.compile(r"\[([^\[\]]{2,40})\]")


@dataclass
class Answer:
    question: str
    text: str
    refused: bool
    refusal_reason: str | None
    citations: list[dict] = field(default_factory=list)
    retrieved_ids: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    mode: str = "hybrid"
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict:
        return asdict(self)


def build_prompt(question: str, hits: list[SearchHit], max_chars: int = 1500) -> str:
    blocks = []
    for hit in hits:
        heading = f"SOURCE [{hit.provision_id}] {hit.title}".rstrip()
        blocks.append(f"{heading}\n{hit.body[:max_chars]}")
    return "\n\n".join(blocks) + f"\n\nQUESTION: {question}"


def extract_citations(text: str, retrieved_ids: list[str]) -> tuple[list[str], list[str]]:
    """Split the IDs the model cited into (valid, invalid).

    Valid means the ID was one of the retrieved sources. Anything else was made
    up or misremembered by the model and must not be shown as a citation.
    """
    allowed = {normalise_id(pid): pid for pid in retrieved_ids}
    valid: list[str] = []
    invalid: list[str] = []
    for raw in _CITATION_RE.findall(text):
        key = normalise_id(raw)
        if key in allowed:
            if allowed[key] not in valid:
                valid.append(allowed[key])
        elif raw not in invalid:
            invalid.append(raw)
    return valid, invalid


def answer_question(
    conn: psycopg.Connection,
    question: str,
    embedder: Embedder,
    llm: ChatLLM,
    mode: str = "hybrid",
    k: int | None = None,
    sourcebook: str | None = None,
    min_similarity: float | None = None,
    log: bool = True,
) -> Answer:
    settings = get_settings()
    k = k or settings.top_k
    min_similarity = settings.min_similarity if min_similarity is None else min_similarity
    started = time.perf_counter()

    hits = search(conn, question, embedder, mode=mode, k=k, sourcebook=sourcebook)
    retrieved_ids = [h.provision_id for h in hits]
    answer = Answer(question=question, text=REFUSAL_TEXT, refused=True, refusal_reason=None,
                    retrieved_ids=retrieved_ids, mode=mode)

    similarities = [h.similarity for h in hits if h.similarity is not None]
    if not hits:
        answer.refusal_reason = "nothing_retrieved"
    elif min_similarity > 0 and similarities and max(similarities) < min_similarity:
        # Cheap refusal: the closest provision is too far away, so skip the model call.
        answer.refusal_reason = "below_similarity_threshold"
    else:
        result = llm.complete(SYSTEM_PROMPT, build_prompt(question, hits))
        answer.prompt_tokens, answer.completion_tokens = result.prompt_tokens, result.completion_tokens
        valid, invalid = extract_citations(result.text, retrieved_ids)
        answer.invalid_citations = invalid
        if NOT_FOUND in result.text:
            answer.refusal_reason = "model_said_not_found"
        elif not valid:
            answer.refusal_reason = "no_valid_citation"
        else:
            by_id = {h.provision_id: h for h in hits}
            answer.text, answer.refused = result.text, False
            answer.citations = [
                {"provision_id": pid, "title": by_id[pid].title, "url": by_id[pid].url,
                 "snippet": by_id[pid].body[:300]}
                for pid in valid
            ]

    answer.latency_ms = int((time.perf_counter() - started) * 1000)
    if log:
        conn.execute(
            """INSERT INTO qa_log (question, mode, retrieved_ids, cited_ids, refused, refusal_reason,
                                   latency_ms, prompt_tokens, completion_tokens)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (question, mode, retrieved_ids, [c["provision_id"] for c in answer.citations], answer.refused,
             answer.refusal_reason, answer.latency_ms, answer.prompt_tokens, answer.completion_tokens),
        )
        conn.commit()
    return answer
