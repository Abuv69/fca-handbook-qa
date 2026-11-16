# Setup, step by step

Work through this once, in order. Each step says what you should see if it worked.

## 0. What you need installed

| Tool | Check it | If missing |
|---|---|---|
| Python 3.11+ | `python3 --version` | python.org |
| Docker Desktop | `docker --version`, and the whale icon is running | docker.com |
| Git | `git --version` | comes with Xcode command line tools on a Mac |

## 1. Create the repository

```bash
unzip fca-handbook-qa.zip && cd fca-handbook-qa
git init -b main && git add . && git commit -m "Project skeleton"
```

Create an empty **private** repository on GitHub called `fca-handbook-qa`, then:

```bash
git remote add origin https://github.com/Abuv69/fca-handbook-qa.git
git push -u origin main
```

Keep it private until week 3. You make it public when the results are yours.

## 2. Install and run the demo

```bash
make install
cp .env.example .env
make up
make demo
```

You should see two snapshots, then a change list like this, then an answer:

```
Snapshot 1: 15 seen, 15 added, 0 changed, 0 removed, 0 unchanged.
Snapshot 2: 15 seen, 1 added, 1 changed, 1 removed, 13 unchanged.
[snapshot 2 ...] changed  DEMO 2.1.1R
    was: A member may borrow a power tool for up to 3 days.
    now: A member may borrow a power tool for up to 5 days.
```

Then run `make test`. All tests should pass, including the integration tests, because the
database is up. Push, open the **Actions** tab on GitHub, and check the same tests go green there.

## 3. Switch on real embeddings

In `.env` set `EMBEDDER=fastembed`. The first run downloads a model of about 100 MB.

```bash
docker compose down -v && make up     # wipes the demo database
make demo
make eval-demo
```

(For real data later, `python -m fcaqa embed --all` re-embeds everything without wiping the
database.)

`hash` embeddings only match shared words. `fastembed` matches meaning. Compare the two
`eval-demo` tables: that difference is the reason vector search exists.

## 4. Connect to the Handbook API

**Never paste your token or password into a chat, an issue or a commit.** It goes in `.env`
only, and `.env` is git-ignored.

1. Sign in at handbook.fca.org.uk in your normal browser and open **Handbook API**.
2. Read the terms and the documentation. Note four things:
   - the base URL
   - how the token is sent (header name, and any prefix such as `Bearer`)
   - the path that returns the provisions of one sourcebook
   - how pagination works, and the rate limit
3. Fill in `.env`:

   ```
   FCA_API_BASE_URL=...
   FCA_API_TOKEN=...
   FCA_API_PROVISIONS_PATH=...        # use {sourcebook} where the code goes, e.g. CONC
   FCA_API_AUTH_HEADER=Authorization  # change if the docs say otherwise
   FCA_API_AUTH_PREFIX=Bearer         # leave empty if the token is sent on its own
   ```

4. Look at one real response without loading anything:

   ```bash
   .venv/bin/python -m fcaqa probe "<a path from the docs>"
   ```

   This prints the shape of the JSON (key names and types, values cut short) and saves the full
   response to `data/raw/_probe/`, which is git-ignored.

5. Make the code match what you saw. There are exactly two places:
   - `FIELD_MAP` in `src/fcaqa/parse.py`: put the API's real key names first in each list.
   - `next_page` in `src/fcaqa/handbook_api.py`: return the next page's URL or path.

   Add a unit test for each change, using a tiny made-up record with the real key names.

6. Load the consumer credit sourcebook:

   ```bash
   .venv/bin/python -m fcaqa ingest --sourcebook CONC
   ```

   If it stops with a data-quality message, read it. It is telling you what is wrong with the
   mapping. Fix that instead of reaching for `--force`.

If the API's structure is very different from one flat list per sourcebook (for example you
must walk chapters, then sections), write that walk in `fetch_sourcebook`. Everything after it
only needs a list of records.

## 5. Connect a language model

Two routes. Pick one.

**Local and free: Ollama.** Install it from ollama.com, pull a small model, then in `.env`:

```
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=<the model name you pulled>
```

**Hosted.** Any provider with an OpenAI-compatible chat-completions endpoint. Set
`LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` from that provider's docs. Set a spending limit
in the provider's dashboard before your first call. A full evaluation run is a few hundred
short calls.

Test it:

```bash
.venv/bin/python -m fcaqa ask "What must a firm assess before entering a regulated credit agreement?" --sourcebook CONC
```

## 6. Run the API and the app

```bash
make api      # http://localhost:8000/docs
make ui       # http://localhost:8501
```

## Troubleshooting

| You see | Cause | Fix |
|---|---|---|
| `connection refused` on port 5432 | Database not running | `make up`, wait 10 seconds |
| `port is already allocated` | Another Postgres on 5432 | Stop it, or change the port in `docker-compose.yml` and `DATABASE_URL` |
| `type "vector" does not exist` | Not the pgvector image | Use `make up`, not a local Postgres |
| `No provisions parsed` | `FIELD_MAP` does not match the API | Run `probe` and fix the key names |
| `401` or `403` from the API | Token or header wrong | Check header name and prefix in the API docs |
| `expected 384 dimensions` | Different embedding model | Use a 384-dimension model, or change `vector(384)` and `EMBED_DIM` together |
| Integration tests skipped | `DATABASE_URL` not set | `cp .env.example .env` and `make up` |
