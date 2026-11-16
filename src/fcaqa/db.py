"""Database helpers. Plain SQL through psycopg, no ORM, so every query is readable."""
from __future__ import annotations

from typing import Sequence

import psycopg
from psycopg.rows import dict_row

from .config import ROOT, get_settings

SCHEMA_PATH = ROOT / "sql" / "schema.sql"


def connect(url: str | None = None) -> psycopg.Connection:
    """Open a connection whose rows come back as dictionaries."""
    return psycopg.connect(url or get_settings().database_url, row_factory=dict_row)


def init_db(conn: psycopg.Connection) -> None:
    """Create tables and indexes. Safe to run again."""
    conn.execute(SCHEMA_PATH.read_text())
    conn.commit()


def vector_literal(vec: Sequence[float]) -> str:
    """Format a list of floats the way pgvector reads it: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
