"""Evaluation: measure the system on questions with known answers.

A question file is JSON Lines, one object per line:
  {"id": "q001", "question": "...", "expected_ids": ["CONC 5.2A.4R"], "answerable": true}
  {"id": "q101", "question": "...", "expected_ids": [], "answerable": false}

Retrieval metrics (answerable questions only):
  hit@k  share of questions where an expected provision is in the top k
  MRR    mean of 1 / rank of the first expected provision (0 if absent)
Answer metrics:
  cited_correct    answerable questions answered with at least one expected provision cited
  false_refusal    answerable questions the system refused
  correct_refusal  unanswerable questions the system refused
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import psycopg

from .answer import answer_question
from .embed import Embedder
from .llm import ChatLLM
from .parse import normalise_id
from .retrieve import MODES, search


def load_questions(path: Path) -> list[dict[str, Any]]:
    questions = []
    for number, line in enumerate(Path(path).read_text().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        item = json.loads(line)
        if "question" not in item:
            raise ValueError(f"{path}:{number} has no 'question'")
        item.setdefault("id", f"q{number:03d}")
        item.setdefault("expected_ids", [])
        item.setdefault("answerable", bool(item["expected_ids"]))
        questions.append(item)
    return questions


def first_hit_rank(expected_ids: Sequence[str], retrieved_ids: Sequence[str]) -> int | None:
    """1-based rank of the first retrieved ID that is expected, or None."""
    expected = {normalise_id(e) for e in expected_ids}
    for rank, retrieved in enumerate(retrieved_ids, start=1):
        if normalise_id(retrieved) in expected:
            return rank
    return None


def retrieval_metrics(ranks: Sequence[int | None], k: int) -> dict[str, float]:
    n = len(ranks)
    if n == 0:
        return {"n": 0, "hit@1": 0.0, f"hit@{k}": 0.0, "mrr": 0.0}
    return {
        "n": n,
        "hit@1": sum(1 for r in ranks if r == 1) / n,
        f"hit@{k}": sum(1 for r in ranks if r is not None and r <= k) / n,
        "mrr": sum(1.0 / r for r in ranks if r is not None) / n,
    }


def answer_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    """rows: {"answerable": bool, "refused": bool, "cited_expected": bool, "latency_ms", tokens}"""
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    share = lambda part, whole: (len(part) / len(whole)) if whole else 0.0
    return {
        "n_answerable": len(answerable),
        "n_unanswerable": len(unanswerable),
        "cited_correct": share([r for r in answerable if not r["refused"] and r["cited_expected"]], answerable),
        "false_refusal": share([r for r in answerable if r["refused"]], answerable),
        "correct_refusal": share([r for r in unanswerable if r["refused"]], unanswerable),
        "avg_latency_ms": (sum(r["latency_ms"] for r in rows) / len(rows)) if rows else 0.0,
        "total_tokens": sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows),
    }


def run_evaluation(
    conn: psycopg.Connection,
    questions: Sequence[dict[str, Any]],
    embedder: Embedder,
    llm: ChatLLM | None,
    modes: Sequence[str] = MODES,
    k: int = 5,
    sourcebook: str | None = None,
) -> dict[str, Any]:
    """Run every question in every mode. Pass llm=None for retrieval-only."""
    report: dict[str, Any] = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "k": k, "n_questions": len(questions), "embedder": embedder.name,
        "llm": llm.name if llm else None, "modes": {},
    }
    for mode in modes:
        ranks: list[int | None] = []
        rows: list[dict[str, Any]] = []
        misses: list[str] = []
        started = time.perf_counter()
        for q in questions:
            if llm is None:
                retrieved = [h.provision_id for h in search(conn, q["question"], embedder, mode, k, sourcebook)]
            else:
                ans = answer_question(conn, q["question"], embedder, llm, mode, k, sourcebook, log=False)
                retrieved = ans.retrieved_ids
                cited = [c["provision_id"] for c in ans.citations]
                rows.append({
                    "answerable": q["answerable"], "refused": ans.refused,
                    "cited_expected": first_hit_rank(q["expected_ids"], cited) is not None,
                    "latency_ms": ans.latency_ms, "prompt_tokens": ans.prompt_tokens,
                    "completion_tokens": ans.completion_tokens,
                })
            if q["answerable"]:
                rank = first_hit_rank(q["expected_ids"], retrieved)
                ranks.append(rank)
                if rank is None:
                    misses.append(q["id"])
        entry: dict[str, Any] = {"retrieval": retrieval_metrics(ranks, k), "retrieval_misses": misses,
                                 "seconds": round(time.perf_counter() - started, 2)}
        if llm is not None:
            entry["answers"] = answer_metrics(rows)
        report["modes"][mode] = entry
    return report


def to_markdown(report: dict[str, Any]) -> str:
    k = report["k"]
    lines = [
        f"Evaluation run {report['run_at']}: {report['n_questions']} questions, k={k}, "
        f"embedder `{report['embedder']}`, model `{report['llm'] or 'none (retrieval only)'}`",
        "",
        f"| Mode | hit@1 | hit@{k} | MRR | Cited correct | False refusal | Correct refusal | Avg latency (ms) | Tokens |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for mode, entry in report["modes"].items():
        r, a = entry["retrieval"], entry.get("answers")
        cells = [mode, f"{r['hit@1']:.0%}", f"{r[f'hit@{k}']:.0%}", f"{r['mrr']:.2f}"]
        if a:
            cells += [f"{a['cited_correct']:.0%}", f"{a['false_refusal']:.0%}", f"{a['correct_refusal']:.0%}",
                      f"{a['avg_latency_ms']:.0f}", str(a["total_tokens"])]
        else:
            cells += ["-"] * 5
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def save_report(report: dict[str, Any], out_dir: Path, label: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"{label}_{stamp}.json"
    md_path = out_dir / f"{label}_latest.md"
    json_path.write_text(json.dumps(report, indent=2))
    md_path.write_text(to_markdown(report))
    return json_path, md_path
