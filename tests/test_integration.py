"""Integration tests: the real pipeline against a real Postgres with pgvector.

They run whenever the database in DATABASE_URL is reachable (locally: `make up`)
and are skipped otherwise. In CI an unreachable database fails the build. Each test works inside its own schema, so your data is safe.
"""
import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from fcaqa import api
from fcaqa.answer import answer_question
from fcaqa.config import ROOT
from fcaqa.db import connect, init_db
from fcaqa.embed import HashEmbedder
from fcaqa.evaluate import load_questions, run_evaluation
from fcaqa.ingest import DataQualityError, ingest_records, load_records, recent_changes
from fcaqa.llm import FakeLLM
from fcaqa.retrieve import search

pytestmark = pytest.mark.integration

try:
    connect().close()
except psycopg.OperationalError as error:
    if os.environ.get("CI"):
        raise  # in CI a missing database is a failure, never a silent skip
    pytest.skip(f"database not reachable, run `make up` first ({error})", allow_module_level=True)

DEMO_V1 = ROOT / "data" / "demo" / "demo_v1.json"
DEMO_V2 = ROOT / "data" / "demo" / "demo_v2.json"


@pytest.fixture()
def conn():
    """A connection pointed at a throwaway schema that is dropped afterwards."""
    schema = f"test_{uuid.uuid4().hex[:10]}"
    connection = connect()
    connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
    connection.execute(f"CREATE SCHEMA {schema}")
    connection.execute(f"SET search_path TO {schema}, public")
    connection.commit()
    init_db(connection)
    yield connection
    connection.rollback()
    connection.execute(f"DROP SCHEMA {schema} CASCADE")
    connection.commit()
    connection.close()


@pytest.fixture()
def loaded(conn):
    ingest_records(conn, "DEMO", load_records(DEMO_V1), "file", HashEmbedder())
    return conn


def test_first_snapshot_adds_everything_and_embeds_it(loaded):
    row = loaded.execute(
        "SELECT count(*) AS n, count(embedding) AS embedded FROM provisions WHERE is_current").fetchone()
    assert row == {"n": 15, "embedded": 15}
    assert recent_changes(loaded) == []  # the initial load is not reported as change


def test_second_snapshot_records_added_changed_and_removed(loaded):
    result = ingest_records(loaded, "DEMO", load_records(DEMO_V2), "file", HashEmbedder())
    assert (result.added, result.changed, result.removed, result.unchanged) == (1, 1, 1, 13)
    changes = {row["provision_id"]: row for row in recent_changes(loaded)}
    assert changes["DEMO 2.1.1R"]["change_type"] == "changed"
    assert "3 days" in changes["DEMO 2.1.1R"]["old_body"] and "5 days" in changes["DEMO 2.1.1R"]["new_body"]
    assert changes["DEMO 3.2.2G"]["change_type"] == "removed"
    assert changes["DEMO 4.1.3R"]["change_type"] == "added"
    # removed provisions stay in the table but are no longer searchable
    hits = search(loaded, "blunt blades normal wear", HashEmbedder(), mode="keyword", k=5)
    assert "DEMO 3.2.2G" not in [h.provision_id for h in hits]


def test_same_snapshot_twice_changes_nothing(loaded):
    result = ingest_records(loaded, "DEMO", load_records(DEMO_V1), "file", HashEmbedder())
    assert (result.added, result.changed, result.removed, result.unchanged) == (0, 0, 0, 15)


def test_partial_download_is_rejected_and_rolled_back(loaded):
    with pytest.raises(DataQualityError):
        ingest_records(loaded, "DEMO", load_records(DEMO_V1)[:3], "file", HashEmbedder())
    assert loaded.execute("SELECT count(*) AS n FROM snapshots").fetchone()["n"] == 1
    assert loaded.execute("SELECT count(*) AS n FROM provisions WHERE is_current").fetchone()["n"] == 15


@pytest.mark.parametrize("mode", ["keyword", "vector", "hybrid"])
def test_every_search_mode_finds_the_late_fee_rule(loaded, mode):
    hits = search(loaded, "late fee per day after the due date", HashEmbedder(), mode=mode, k=3)
    assert hits and hits[0].provision_id == "DEMO 3.1.1R"


def test_keyword_search_with_only_stop_words_returns_nothing(loaded):
    assert search(loaded, "the of and", HashEmbedder(), mode="keyword", k=3) == []


def test_answer_cites_a_retrieved_provision_and_is_logged(loaded):
    answer = answer_question(loaded, "How long can I borrow a power tool?", HashEmbedder(), FakeLLM(), sourcebook="DEMO")
    assert not answer.refused
    assert answer.citations[0]["provision_id"] in answer.retrieved_ids
    assert loaded.execute("SELECT count(*) AS n FROM qa_log").fetchone()["n"] == 1


def test_similarity_threshold_refuses_without_calling_the_model(loaded):
    class ExplodingLLM:
        name = "exploding"

        def complete(self, system, user):
            raise AssertionError("the model must not be called")

    answer = answer_question(loaded, "zebra quantum xylophone", HashEmbedder(), ExplodingLLM(),
                             mode="vector", min_similarity=0.99)
    assert answer.refused and answer.refusal_reason == "below_similarity_threshold"


def test_demo_evaluation_reaches_a_sensible_hit_rate(loaded):
    questions = load_questions(ROOT / "eval" / "questions.demo.jsonl")
    report = run_evaluation(loaded, questions, HashEmbedder(), None, modes=["keyword", "hybrid"], k=5)
    assert report["modes"]["keyword"]["retrieval"]["n"] == 10
    assert report["modes"]["hybrid"]["retrieval"]["hit@5"] >= 0.7


def test_http_api(loaded, monkeypatch):
    monkeypatch.setattr(api, "connect", lambda: _Borrowed(loaded))
    monkeypatch.setattr(api, "embedder", lambda: HashEmbedder())
    monkeypatch.setattr(api, "llm", lambda: FakeLLM())
    client = TestClient(api.app)
    assert client.get("/health").json()["provisions"] == 15
    body = client.post("/ask", json={"question": "How many items can I hold?", "sourcebook": "DEMO"}).json()
    assert body["refused"] is False and body["citations"]
    assert client.get("/provisions/demo 2.2.1r").json()["provision_id"] == "DEMO 2.2.1R"
    assert client.get("/provisions/NOPE 1.1.1R").status_code == 404
    assert client.post("/ask", json={"question": "x"}).status_code == 422


class _Borrowed:
    """Lets the API use the test connection in a `with` block without closing it."""

    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self._connection

    def __exit__(self, *exc):
        return False
