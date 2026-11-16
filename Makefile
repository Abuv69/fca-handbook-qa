.PHONY: install up down init demo test eval-demo api ui

install:        ## create a virtualenv and install the project
	python3 -m venv .venv && .venv/bin/pip install -e ".[ui,dev]"

up:             ## start Postgres (with pgvector) in Docker
	docker compose up -d db

down:
	docker compose down

init:           ## create the tables (safe to re-run)
	.venv/bin/python -m fcaqa init-db

demo: init      ## load the synthetic demo rulebook twice to show change tracking
	.venv/bin/python -m fcaqa ingest --sourcebook DEMO --from-file data/demo/demo_v1.json
	.venv/bin/python -m fcaqa ingest --sourcebook DEMO --from-file data/demo/demo_v2.json
	.venv/bin/python -m fcaqa changes
	.venv/bin/python -m fcaqa ask "How long can I borrow a power tool?" --sourcebook DEMO

test:
	.venv/bin/pytest -q

eval-demo:
	.venv/bin/python -m fcaqa eval eval/questions.demo.jsonl --sourcebook DEMO --retrieval-only --label demo

api:
	.venv/bin/uvicorn fcaqa.api:app --reload

ui:
	.venv/bin/streamlit run app/streamlit_app.py
