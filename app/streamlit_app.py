"""Small web UI. Run with:  streamlit run app/streamlit_app.py"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from fcaqa.answer import DISCLAIMER, answer_question
from fcaqa.db import connect
from fcaqa.embed import get_embedder
from fcaqa.ingest import recent_changes
from fcaqa.llm import get_llm

RESULTS_DIR = Path(__file__).resolve().parents[1] / "eval" / "results"

st.set_page_config(page_title="FCA Handbook Q&A", page_icon="📘", layout="centered")


@st.cache_resource
def resources():
    return get_embedder(), get_llm()


st.title("FCA Handbook Q&A")
st.caption(f"Answers cite the provision they come from, or the app declines to answer. {DISCLAIMER}")

ask_tab, changes_tab, eval_tab = st.tabs(["Ask", "What changed", "How good is it?"])

with ask_tab:
    question = st.text_input("Your question", placeholder="e.g. What must a firm do before agreeing a loan?")
    mode = st.radio("Search mode", ["hybrid", "keyword", "vector"], horizontal=True)
    if question:
        embedder, llm = resources()
        with connect() as conn, st.spinner("Searching the provisions..."):
            answer = answer_question(conn, question, embedder, llm, mode=mode)
        if answer.refused:
            st.warning(f"{answer.text}  \n_Reason: {answer.refusal_reason}_")
        else:
            st.success(answer.text)
            st.subheader("Sources")
            for citation in answer.citations:
                label = f"**{citation['provision_id']}** {citation['title']}"
                if citation["url"]:
                    label += f" ([official text]({citation['url']}))"
                st.markdown(label)
                st.caption(citation["snippet"])
        st.caption(f"Retrieved: {', '.join(answer.retrieved_ids) or 'nothing'} · {answer.latency_ms} ms")

with changes_tab:
    st.write("Provisions added, changed or removed between snapshots.")
    with connect() as conn:
        rows = recent_changes(conn, 100)
    if not rows:
        st.info("No changes yet. They appear after the second snapshot of a sourcebook.")
    for row in rows:
        with st.expander(f"{row['taken_at']:%d %b %Y} · {row['change_type']} · {row['provision_id']}"):
            if row["old_body"]:
                st.markdown("**Before**")
                st.write(row["old_body"])
            if row["change_type"] != "removed":
                st.markdown("**Now**")
                st.write(row["new_body"])

with eval_tab:
    reports = sorted(RESULTS_DIR.glob("*_latest.md"))
    if not reports:
        st.info("No evaluation results yet. Run `python -m fcaqa eval ...`.")
    for report in reports:
        st.markdown(report.read_text())
