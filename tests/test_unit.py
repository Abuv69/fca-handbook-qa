"""Unit tests: no database, no network, no model. They run in under a second."""
import httpx
import pytest

from fcaqa.answer import build_prompt, extract_citations
from fcaqa.embed import HashEmbedder
from fcaqa.evaluate import answer_metrics, first_hit_rank, retrieval_metrics
from fcaqa.handbook_api import HandbookApiError, HandbookClient, describe
from fcaqa.ingest import DataQualityError, quality_checks
from fcaqa.llm import FakeLLM, OpenAICompatibleLLM
from fcaqa.parse import clean_text, find_items, normalise_id, parse_records, provision_from_raw, split_id
from fcaqa.retrieve import SearchHit, reciprocal_rank_fusion


# ---------- parse ----------
def test_clean_text_strips_html_and_whitespace():
    assert clean_text("<p>A firm&nbsp;must   <b>not</b></p><p>mislead.</p>") == "A firm must not mislead."


def test_normalise_id_is_case_and_space_insensitive():
    assert normalise_id("conc 5.2a.4 r") == "CONC 5.2A.4R"
    assert normalise_id("CONC  5.2A.4R") == "CONC 5.2A.4R"


def test_split_id_reads_chapter_section_and_type():
    assert split_id("CONC 5.2A.4R") == {
        "sourcebook": "CONC", "chapter": "5", "section": "5.2A", "provision_type": "R"}
    assert split_id("SYSC 4.1.1AR")["provision_type"] == "R"   # paragraph 1A, type R
    assert split_id("CONC 2.5A.3UK")["provision_type"] == "UK"
    assert split_id("CONC 1.1.1")["provision_type"] is None
    assert split_id("CONC SCH1")["chapter"] is None             # unknown shapes do not crash


def test_provision_from_raw_uses_alternative_keys_and_hash_changes_with_content():
    a = provision_from_raw({"reference": "CONC 1.1.1G", "heading": "Scope", "text": "<p>Applies to firms.</p>"})
    b = provision_from_raw({"reference": "CONC 1.1.1G", "heading": "Scope", "text": "Applies to all firms."})
    assert (a.provision_id, a.sourcebook, a.provision_type, a.body) == ("CONC 1.1.1G", "CONC", "G", "Applies to firms.")
    assert a.content_hash != b.content_hash
    assert provision_from_raw({"text": "no id"}) is None


def test_find_items_handles_wrappers():
    records = [{"id": "X 1.1.1R"}]
    assert find_items(records) == records
    assert find_items({"items": records}) == records
    assert find_items({"meta": {}, "somethingElse": records}) == records
    assert find_items({"count": 0}) == []


# ---------- data quality ----------
def _provisions(n, body="text"):
    return parse_records([{"provision_id": f"DEMO 1.1.{i}R", "body": body} for i in range(1, n + 1)])


def test_quality_checks_reject_empty_duplicate_and_shrunken_batches():
    with pytest.raises(DataQualityError):
        quality_checks([], current_count=0)
    with pytest.raises(DataQualityError, match="duplicate"):
        quality_checks(_provisions(2) + _provisions(1), current_count=0)
    with pytest.raises(DataQualityError, match="drop"):
        quality_checks(_provisions(5), current_count=100)
    kept, warnings = quality_checks(_provisions(5), current_count=100, force=True)
    assert len(kept) == 5 and warnings


def test_quality_checks_skip_empty_bodies_with_a_warning():
    kept, warnings = quality_checks(_provisions(3) + parse_records([{"provision_id": "DEMO 9.9.9R", "body": ""}]), 0)
    assert len(kept) == 3 and "empty body" in warnings[0]


# ---------- retrieval ----------
def test_rrf_rewards_items_ranked_well_in_both_lists():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]])
    ids = [item for item, _ in fused]
    assert set(ids[:2]) == {"a", "b"} and set(ids[2:]) == {"c", "d"}
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62)


def test_hash_embedder_is_deterministic_normalised_and_word_sensitive():
    e = HashEmbedder()
    a, b, c = e.embed(["late fee per day", "late fee per day", "chainsaw safety induction"])
    dot = lambda x, y: sum(i * j for i, j in zip(x, y))
    assert a == b and len(a) == 384
    assert dot(a, a) == pytest.approx(1.0)
    assert dot(a, c) < 0.5


# ---------- answering ----------
def _hit(pid, body="Body text."):
    return SearchHit(pid, "DEMO", "R", "Title", body, None, 1.0)


def test_extract_citations_separates_real_from_invented():
    valid, invalid = extract_citations(
        "Up to 3 days [demo 2.1.1r]. Also see [DEMO 9.9.9R] and [DEMO 2.1.1R].", ["DEMO 2.1.1R", "DEMO 2.1.2R"])
    assert valid == ["DEMO 2.1.1R"] and invalid == ["DEMO 9.9.9R"]


def test_fake_llm_quotes_top_source_from_prompt():
    prompt = build_prompt("How long?", [_hit("DEMO 2.1.1R", "Up to 3 days. More text."), _hit("DEMO 2.1.2R")])
    assert FakeLLM().complete("system", prompt).text == "Up to 3 days. [DEMO 2.1.1R]"
    assert FakeLLM().complete("system", "QUESTION: anything").text == "NOT_FOUND"


def test_openai_compatible_llm_parses_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, json={"choices": [{"message": {"content": " Hello [A 1.1.1R] "}}],
                                         "usage": {"prompt_tokens": 12, "completion_tokens": 3}})
    llm = OpenAICompatibleLLM("http://test/v1", "key", "some-model", transport=httpx.MockTransport(handler))
    result = llm.complete("s", "u")
    assert (result.text, result.prompt_tokens, result.completion_tokens) == ("Hello [A 1.1.1R]", 12, 3)


# ---------- evaluation ----------
def test_first_hit_rank_and_retrieval_metrics():
    assert first_hit_rank(["DEMO 2.1.1R"], ["DEMO 1.1.1R", "demo 2.1.1r"]) == 2
    assert first_hit_rank(["DEMO 2.1.1R"], ["DEMO 1.1.1R"]) is None
    metrics = retrieval_metrics([1, 2, None, 6], k=5)
    assert metrics["hit@1"] == 0.25 and metrics["hit@5"] == 0.5
    assert metrics["mrr"] == pytest.approx((1 + 0.5 + 0 + 1 / 6) / 4)


def test_answer_metrics_counts_refusals_correctly():
    row = lambda answerable, refused, cited: {"answerable": answerable, "refused": refused, "cited_expected": cited,
                                             "latency_ms": 100, "prompt_tokens": 10, "completion_tokens": 5}
    metrics = answer_metrics([row(True, False, True), row(True, True, False), row(False, True, False), row(False, False, False)])
    assert metrics["cited_correct"] == 0.5 and metrics["false_refusal"] == 0.5
    assert metrics["correct_refusal"] == 0.5 and metrics["total_tokens"] == 60


# ---------- API client ----------
def _client(handler, **kwargs):
    return HandbookClient("https://api.test", "tok", transport=httpx.MockTransport(handler), sleep=lambda s: None, **kwargs)


def test_client_sends_token_retries_on_429_and_follows_pages():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer tok"
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        if request.url.path == "/books/CONC":
            return httpx.Response(200, json={"items": [{"id": "CONC 1.1.1R"}], "next": "/books/CONC/2"})
        return httpx.Response(200, json={"items": [{"id": "CONC 1.1.2R"}]})

    pages = _client(handler).fetch_sourcebook("CONC", "/books/{sourcebook}")
    assert calls == ["/books/CONC", "/books/CONC", "/books/CONC/2"]
    assert [find_items(p)[0]["id"] for p in pages] == ["CONC 1.1.1R", "CONC 1.1.2R"]


def test_client_explains_auth_failures_and_missing_config():
    with pytest.raises(HandbookApiError, match="FCA_API_TOKEN"):
        _client(lambda request: httpx.Response(401)).get_json("/x")
    with pytest.raises(HandbookApiError):
        HandbookClient("", "")


def test_describe_shows_shape_not_full_content():
    text = describe({"items": [{"reference": "CONC 1.1.1R", "text": "x" * 500}], "total": 1})
    assert "list of 1" in text and "reference" in text and "x" * 60 not in text
