"""Command line entry point:  python -m fcaqa <command>

  init-db                         create tables
  probe PATH                      call one API path and show the shape of the response
  ingest --sourcebook CONC        snapshot a sourcebook from the API
  ingest --sourcebook DEMO --from-file data/demo/demo_v1.json
  embed [--all]                   embed provisions (--all after changing the embedding model)
  changes                         what changed between snapshots
  ask "question"                  answer one question
  eval FILE                       run the evaluation
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ROOT, get_settings


def _cmd_init_db(args: argparse.Namespace) -> int:
    from .db import connect, init_db

    with connect() as conn:
        init_db(conn)
    print("Database ready.")
    return 0


def _cmd_probe(args: argparse.Namespace) -> int:
    from .handbook_api import HandbookClient, describe
    from .parse import find_items

    client = HandbookClient.from_settings()
    payload = client.get_json(args.path)
    out = get_settings().raw_dir / "_probe" / "last_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(describe(payload))
    print(f"\nRecords found by find_items(): {len(find_items(payload))}")
    print(f"Next page detected: {HandbookClient.next_page(payload)}")
    print(f"Full response saved to {out} (git-ignored).")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    from .db import connect
    from .embed import get_embedder
    from .handbook_api import HandbookClient
    from .ingest import DataQualityError, ingest_records, load_records, save_raw
    from .parse import find_items

    sourcebook = args.sourcebook.upper()
    if args.from_file:
        records, source, raw_path = load_records(Path(args.from_file)), "file", str(args.from_file)
    else:
        client = HandbookClient.from_settings()
        pages = client.fetch_sourcebook(sourcebook)
        raw_path = str(save_raw(pages, sourcebook, get_settings().raw_dir))  # raw first, always
        records = [item for page in pages for item in find_items(page)]
        source = "api"
        print(f"Fetched {len(pages)} page(s), {len(records)} records. Raw copy: {raw_path}")

    with connect() as conn:
        try:
            result = ingest_records(conn, sourcebook, records, source, get_embedder(), raw_path, args.force)
        except DataQualityError as error:
            print(f"STOPPED by a data-quality check: {error}", file=sys.stderr)
            return 2
    for warning in result.warnings:
        print(f"warning: {warning}")
    print(
        f"Snapshot {result.snapshot_id}: {result.seen} seen, {result.added} added, "
        f"{result.changed} changed, {result.removed} removed, {result.unchanged} unchanged."
    )
    return 0


def _cmd_embed(args: argparse.Namespace) -> int:
    from .db import connect
    from .embed import get_embedder
    from .ingest import embed_missing

    with connect() as conn:
        if args.all:
            conn.execute("UPDATE provisions SET embedding = NULL")
            conn.commit()
        count = embed_missing(conn, get_embedder())
    print(f"Embedded {count} provisions.")
    return 0


def _cmd_changes(args: argparse.Namespace) -> int:
    from .db import connect
    from .ingest import recent_changes

    with connect() as conn:
        rows = recent_changes(conn, args.limit, args.include_initial)
    if not rows:
        print("No changes recorded yet (the first snapshot of a sourcebook is not listed).")
    for row in rows:
        print(f"[snapshot {row['snapshot_id']} {row['taken_at']:%Y-%m-%d}] {row['change_type']:8} {row['provision_id']}")
        if row["change_type"] == "changed":
            print(f"    was: {row['old_body'][:110]}")
            print(f"    now: {(row['new_body'] or '')[:110]}")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    from .answer import answer_question
    from .db import connect
    from .embed import get_embedder
    from .llm import get_llm

    with connect() as conn:
        answer = answer_question(conn, args.question, get_embedder(), get_llm(), args.mode, args.k, args.sourcebook)
    if args.json:
        print(json.dumps(answer.to_dict(), indent=2))
        return 0
    print(answer.text)
    for citation in answer.citations:
        print(f"  - {citation['provision_id']}: {citation['snippet'][:100]}")
    if answer.refused:
        print(f"  (refused: {answer.refusal_reason})")
    print(f"  retrieved: {', '.join(answer.retrieved_ids)}  [{answer.latency_ms} ms]")
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    from .db import connect
    from .embed import get_embedder
    from .evaluate import load_questions, run_evaluation, save_report, to_markdown
    from .llm import get_llm

    questions = load_questions(Path(args.file))
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    llm = None if args.retrieval_only else get_llm()
    with connect() as conn:
        report = run_evaluation(conn, questions, get_embedder(), llm, modes, args.k, args.sourcebook)
    json_path, md_path = save_report(report, ROOT / "eval" / "results", args.label)
    print(to_markdown(report))
    print(f"Saved {json_path} and {md_path}")
    if args.min_hit is not None:
        best = max(entry["retrieval"][f"hit@{args.k}"] for entry in report["modes"].values())
        if best < args.min_hit:
            print(f"FAIL: best hit@{args.k} {best:.0%} is below the required {args.min_hit:.0%}", file=sys.stderr)
            return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fcaqa", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=_cmd_init_db)

    probe = sub.add_parser("probe")
    probe.add_argument("path")
    probe.set_defaults(func=_cmd_probe)

    ingest = sub.add_parser("ingest")
    ingest.add_argument("--sourcebook", required=True)
    ingest.add_argument("--from-file")
    ingest.add_argument("--force", action="store_true", help="accept a large drop in provision count")
    ingest.set_defaults(func=_cmd_ingest)

    embed = sub.add_parser("embed")
    embed.add_argument("--all", action="store_true", help="re-embed everything")
    embed.set_defaults(func=_cmd_embed)

    changes = sub.add_parser("changes")
    changes.add_argument("--limit", type=int, default=50)
    changes.add_argument("--include-initial", action="store_true")
    changes.set_defaults(func=_cmd_changes)

    ask = sub.add_parser("ask")
    ask.add_argument("question")
    ask.add_argument("--mode", default="hybrid", choices=["keyword", "vector", "hybrid"])
    ask.add_argument("--k", type=int, default=None)
    ask.add_argument("--sourcebook")
    ask.add_argument("--json", action="store_true")
    ask.set_defaults(func=_cmd_ask)

    evaluate = sub.add_parser("eval")
    evaluate.add_argument("file")
    evaluate.add_argument("--modes", default="keyword,vector,hybrid")
    evaluate.add_argument("--k", type=int, default=5)
    evaluate.add_argument("--sourcebook")
    evaluate.add_argument("--retrieval-only", action="store_true", help="skip the language model")
    evaluate.add_argument("--label", default="eval")
    evaluate.add_argument("--min-hit", type=float, default=None, help="exit 1 if best hit@k is below this (0-1)")
    evaluate.set_defaults(func=_cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    from .handbook_api import HandbookApiError

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except HandbookApiError as error:
        print(f"Handbook API problem: {error}", file=sys.stderr)
        return 2
