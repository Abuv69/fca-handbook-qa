# What to learn, and where

Ordered by when you need it. Learn each thing just before the session that uses it, for the
time shown, then go and use it. Do not finish a course before starting the project.

Your starting point: solid Python, SQL, pandas, pytest, GitHub Actions and AWS basics.
The gaps this project fills are marked **new**.

## Week 0 and 1

### Docker and Docker Compose (**new**), about 3 hours
You need: images against containers, ports, volumes, `docker compose up/down`, reading logs.
- Docker's own getting-started guide: https://docs.docker.com/get-started/
- Compose overview: https://docs.docker.com/compose/
- Then read this project's `docker-compose.yml` line by line and explain each key.

### PostgreSQL beyond the basics (**new**), about 3 hours
You know SQL from SQLite and MySQL. New here: `psql`, transactions, `ON CONFLICT` upserts,
generated columns, array columns, indexes.
- Run `docker compose exec db psql -U fca` and explore with `\dt`, `\d provisions`.
- Upsert: https://www.postgresql.org/docs/current/sql-insert.html (the ON CONFLICT section)
- psycopg 3 basics: https://www.psycopg.org/psycopg3/docs/basic/usage.html

### Calling an API properly, about 1 hour
Auth headers, pagination, rate limits, retries with backoff.
- httpx quickstart: https://www.python-httpx.org/quickstart/
- Read `handbook_api.py` and its tests, which fake the server with `httpx.MockTransport`.

## Week 2

### Full-text search in Postgres (**new**), about 2 hours
`tsvector`, `tsquery`, stemming, ranking.
- https://www.postgresql.org/docs/current/textsearch-intro.html
- Try in `psql`: `SELECT to_tsvector('english', 'Firms must assess creditworthiness');`

### Embeddings and vector search (**new**), about 3 hours
What an embedding is, cosine similarity, nearest-neighbour indexes.
- pgvector README, top to "Indexing": https://github.com/pgvector/pgvector
- fastembed README: https://github.com/qdrant/fastembed
- LLM Zoomcamp, the vector search module: https://github.com/DataTalksClub/llm-zoomcamp

### Retrieval-augmented generation (**new**), about 4 hours
- LLM Zoomcamp module 1 (introduction to RAG). Free, with videos and code. It builds the same
  three steps this project has: search, build a prompt, call the model.
- Then read `answer.py`. It is under 150 lines.

### Evaluating retrieval and answers (**new**), about 3 hours
The part most portfolio projects skip, and the part interviewers ask about.
- LLM Zoomcamp, the evaluation module (hit rate, MRR, judging answers).
- Reciprocal rank fusion: Cormack, Clarke and Buettcher (2009), "Reciprocal rank fusion
  outperforms Condorcet and individual rank learning methods", SIGIR. Two pages. Read it, then
  read `reciprocal_rank_fusion` in `retrieve.py`. They are the same formula.
- Read `evaluate.py` and `tests/test_unit.py` together.

### Running a model locally, about 1 hour
- https://ollama.com (install, pull a small model, it serves an OpenAI-compatible endpoint)

## Week 3

### FastAPI (**new**), about 3 hours
- Official tutorial, first eight sections: https://fastapi.tiangolo.com/tutorial/
- Then open http://localhost:8000/docs and call your own endpoints.

### Deploying (**new**), about 2 hours
- Streamlit deployment docs: https://docs.streamlit.io
- You have deployed Streamlit before. The new part is a hosted database and secrets.

## For the gold and silver project (later)

### dbt (**new**), about 5 hours
- dbt Fundamentals, free from dbt Labs: https://www.getdbt.com/dbt-learn

### Orchestration (**new**), about 5 hours
- Dagster Essentials, free: https://courses.dagster.io/courses/dagster-essentials
- Or the Airflow module of the Data Engineering Zoomcamp:
  https://github.com/DataTalksClub/data-engineering-zoomcamp

### Dimensional modelling, about 2 hours
- The Data Engineering Zoomcamp analytics engineering module covers staging, facts and
  dimensions with dbt.

## How to study so it sticks

1. Read or watch for 30 to 45 minutes.
2. Close it. Write five lines in `docs/NOTES.md` from memory.
3. Use the idea in the project the same day.
4. At the end of each week, answer that week's "explain out loud" questions in `PLAN.md`.
