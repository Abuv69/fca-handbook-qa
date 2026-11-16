"""Ingestion: raw payload -> quality checks -> upsert -> change log -> embeddings.

Each run is a snapshot. Comparing a snapshot with what is already stored tells us
which provisions were added, changed or removed since last time.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import psycopg

from .db import vector_literal
from .embed import Embedder
from .parse import Provision, find_items, parse_records

MAX_EMBED_CHARS = 2000


class DataQualityError(RuntimeError):
    """The incoming data looks wrong, so nothing was written."""


@dataclass
class SnapshotResult:
    snapshot_id: int
    seen: int = 0
    added: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0
    warnings: list[str] = field(default_factory=list)


def save_raw(payload: Any, sourcebook: str, raw_dir: Path) -> Path:
    """Write the untouched payload to disk first, so any run can be replayed."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = raw_dir / sourcebook.upper() / f"{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False))
    return path


def load_records(path: Path) -> list[dict[str, Any]]:
    """Read records from a saved payload: one page, or a list of pages."""
    payload = json.loads(Path(path).read_text())
    items = find_items(payload)
    if not items and isinstance(payload, list):  # a list of pages
        for page in payload:
            items.extend(find_items(page))
    return items


def quality_checks(
    provisions: Sequence[Provision], current_count: int, max_drop: float = 0.2, force: bool = False
) -> tuple[list[Provision], list[str]]:
    """Reject bad batches before they touch the database.

    Returns the provisions worth keeping and a list of warnings. Raises
    DataQualityError for problems that should stop the run.
    """
    warnings: list[str] = []
    if not provisions:
        raise DataQualityError("No provisions parsed. Check FIELD_MAP in parse.py against the payload.")

    seen: set[str] = set()
    duplicates: list[str] = []
    for p in provisions:
        if p.provision_id in seen:
            duplicates.append(p.provision_id)
        seen.add(p.provision_id)
    if duplicates:
        raise DataQualityError(
            f"{len(duplicates)} duplicate provision IDs, e.g. {duplicates[:5]}. "
            "IDs must be unique within a snapshot."
        )

    kept = [p for p in provisions if p.body]
    empty = len(provisions) - len(kept)
    if empty:
        warnings.append(f"Skipped {empty} provisions with an empty body.")
    if not kept:
        raise DataQualityError("Every provision had an empty body. Check the 'body' keys in FIELD_MAP.")

    if current_count and len(kept) < current_count * (1 - max_drop):
        message = (
            f"Snapshot has {len(kept)} provisions but {current_count} are stored: a drop of more than "
            f"{max_drop:.0%}. This usually means a partial download."
        )
        if not force:
            raise DataQualityError(message + " Re-run with --force if the drop is real.")
        warnings.append(message + " Continuing because --force was given.")
    return kept, warnings


def run_snapshot(
    conn: psycopg.Connection,
    sourcebook: str,
    provisions: Sequence[Provision],
    source: str,
    raw_path: str | None = None,
    force: bool = False,
) -> SnapshotResult:
    """Apply one snapshot inside a single transaction. All of it lands, or none of it."""
    sourcebook = sourcebook.upper()
    with conn.transaction():
        rows = conn.execute(
            "SELECT provision_id, content_hash, body, is_current FROM provisions WHERE sourcebook = %s",
            (sourcebook,),
        ).fetchall()
        stored = {row["provision_id"]: row for row in rows}
        current_ids = {pid for pid, row in stored.items() if row["is_current"]}

        kept, warnings = quality_checks(provisions, len(current_ids), force=force)

        snapshot_id = conn.execute(
            "INSERT INTO snapshots (source, sourcebook, raw_path) VALUES (%s, %s, %s) RETURNING snapshot_id",
            (source, sourcebook, raw_path),
        ).fetchone()["snapshot_id"]
        result = SnapshotResult(snapshot_id=snapshot_id, seen=len(kept), warnings=warnings)

        for p in kept:
            old = stored.get(p.provision_id)
            if old and old["is_current"] and old["content_hash"] == p.content_hash:
                result.unchanged += 1
                continue
            change_type = "changed" if old and old["is_current"] else "added"
            conn.execute(
                """
                INSERT INTO provisions (provision_id, sourcebook, chapter, section, provision_type,
                                        title, body, url, content_hash, is_current,
                                        first_seen_snapshot, last_changed_snapshot, embedding)
                VALUES (%(id)s, %(book)s, %(chapter)s, %(section)s, %(type)s, %(title)s, %(body)s,
                        %(url)s, %(hash)s, TRUE, %(snap)s, %(snap)s, NULL)
                ON CONFLICT (provision_id) DO UPDATE SET
                    chapter = EXCLUDED.chapter, section = EXCLUDED.section,
                    provision_type = EXCLUDED.provision_type, title = EXCLUDED.title,
                    body = EXCLUDED.body, url = EXCLUDED.url, content_hash = EXCLUDED.content_hash,
                    is_current = TRUE, last_changed_snapshot = EXCLUDED.last_changed_snapshot,
                    embedding = NULL
                """,
                {
                    "id": p.provision_id, "book": sourcebook, "chapter": p.chapter, "section": p.section,
                    "type": p.provision_type, "title": p.title, "body": p.body, "url": p.url,
                    "hash": p.content_hash, "snap": snapshot_id,
                },
            )
            conn.execute(
                """INSERT INTO provision_changes (snapshot_id, provision_id, change_type, old_hash, new_hash, old_body)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    snapshot_id, p.provision_id, change_type,
                    old["content_hash"] if old else None, p.content_hash,
                    old["body"] if change_type == "changed" else None,
                ),
            )
            if change_type == "changed":
                result.changed += 1
            else:
                result.added += 1

        gone = current_ids - {p.provision_id for p in kept}
        for provision_id in sorted(gone):
            conn.execute(
                "UPDATE provisions SET is_current = FALSE, last_changed_snapshot = %s WHERE provision_id = %s",
                (snapshot_id, provision_id),
            )
            conn.execute(
                """INSERT INTO provision_changes (snapshot_id, provision_id, change_type, old_hash, old_body)
                   VALUES (%s, %s, 'removed', %s, %s)""",
                (snapshot_id, provision_id, stored[provision_id]["content_hash"], stored[provision_id]["body"]),
            )
        result.removed = len(gone)

        conn.execute(
            "UPDATE snapshots SET provisions_seen = %s, added = %s, changed = %s, removed = %s WHERE snapshot_id = %s",
            (result.seen, result.added, result.changed, result.removed, snapshot_id),
        )
    return result


def embed_missing(conn: psycopg.Connection, embedder: Embedder, batch_size: int = 64) -> int:
    """Embed every current provision that has no embedding yet (new or changed ones)."""
    rows = conn.execute(
        "SELECT provision_id, title, body FROM provisions WHERE is_current AND embedding IS NULL ORDER BY provision_id"
    ).fetchall()
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        texts = [f"{r['provision_id']} {r['title'] or ''}\n{r['body']}"[:MAX_EMBED_CHARS] for r in batch]
        for row, vec in zip(batch, embedder.embed(texts)):
            conn.execute(
                "UPDATE provisions SET embedding = %s::vector WHERE provision_id = %s",
                (vector_literal(vec), row["provision_id"]),
            )
        conn.commit()
    return len(rows)


def ingest_records(
    conn: psycopg.Connection,
    sourcebook: str,
    records: Sequence[dict[str, Any]],
    source: str,
    embedder: Embedder,
    raw_path: str | None = None,
    force: bool = False,
) -> SnapshotResult:
    """The whole pipeline for records that are already in memory."""
    provisions = parse_records(records, sourcebook)
    result = run_snapshot(conn, sourcebook, provisions, source, raw_path, force)
    conn.commit()
    embed_missing(conn, embedder)
    return result


def recent_changes(conn: psycopg.Connection, limit: int = 50, include_initial: bool = False) -> list[dict]:
    """Latest changes. The first snapshot of a sourcebook is skipped by default, since
    everything in it counts as 'added'."""
    return conn.execute(
        """
        SELECT c.change_id, c.snapshot_id, s.taken_at, s.sourcebook, c.provision_id, c.change_type,
               c.old_body, p.body AS new_body
        FROM provision_changes c
        JOIN snapshots s USING (snapshot_id)
        LEFT JOIN provisions p USING (provision_id)
        WHERE %(initial)s OR c.snapshot_id > (
            SELECT min(snapshot_id) FROM snapshots first WHERE first.sourcebook = s.sourcebook
        )
        ORDER BY c.change_id DESC
        LIMIT %(limit)s
        """,
        {"initial": include_initial, "limit": limit},
    ).fetchall()
