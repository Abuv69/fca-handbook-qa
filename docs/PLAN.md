# Project plan: FCA Handbook Q&A

Three weeks at about 10 hours a week, sized to fit around your final-year project, two jobs
and applications. Sessions are 1 to 2 hours. Tick them off as you go.

**Standing item every week:** 5 applications and 5 cold emails a day on weekdays. The project
supports the job search. It does not replace it.

## The one rule

The code in this repository runs, but it is not yours until you can explain it and have
changed it. An interviewer will open a file and ask "why did you do it this way?".

So for every module: read it, run it, break it on purpose, then answer the questions listed
under that week **out loud, without looking**. If you cannot, you are not finished with it.
Be ready to say plainly how you used AI tools while building. Employers ask, and "I used it to
scaffold, then I wrote the evaluation set, did the API integration and ran the experiments
myself" is a good answer because it is true.

## What is deliberately left for you

These cannot be done by anyone else, and they are the parts worth talking about.

1. **The API integration.** The endpoint paths and field names are behind your login.
2. **The evaluation set.** About 100 answerable questions and 20 out-of-scope ones, each with
   provision IDs you have checked yourself.
3. **The experiments.** Which search mode wins, what threshold to refuse at, and why.
4. **One extension**, chosen in week 3.
5. **The Results and "what I learned" sections** of the README.

## Done means

- [ ] Real sourcebook loaded through the API, at least two snapshots a week apart
- [ ] Evaluation table in the README with your numbers for all three search modes
- [ ] Out-of-scope questions refused at a rate you can state
- [ ] Tests green in GitHub Actions
- [ ] App deployed, link on your CV and LinkedIn
- [ ] One LinkedIn post with one honest number

---

## Week 0: this weekend (2 hours)

- [ ] Follow `docs/SETUP.md` steps 0 to 3. Demo runs, tests pass locally and in Actions.
- [ ] Read `sql/schema.sql` top to bottom. Draw the four tables on paper.
- [ ] Read the FCA Handbook API terms. Write down in `docs/NOTES.md` what they allow, the rate
      limit, and anything you are unsure about. If reuse is unclear, email the FCA and ask.

## Week 1 (16 to 22 Nov): data in

- [ ] **S1. API first contact.** SETUP step 4, parts 1 to 4. Save nothing to git. Write the
      endpoint notes in `docs/NOTES.md` (no token).
- [ ] **S2. Mapping.** Fix `FIELD_MAP` and `next_page`. Add a unit test for each.
- [ ] **S3. First real ingest.** Load CONC. Then check it with SQL in `psql`:
      how many provisions, how many per chapter, how many of each type, the five longest,
      any with very short bodies. Write what you find in `docs/NOTES.md`.
- [ ] **S4. Break it.** Edit a saved raw file to delete half the records and ingest it with
      `--from-file`. Watch the quality check stop it. Then duplicate an ID. Then read
      `quality_checks` and `run_snapshot` until both behaviours make sense.
- [ ] **S5. Schedule it.** Add a GitHub Actions workflow on a weekly `schedule` that runs the
      ingest against a hosted database, or run it by hand every Sunday for now. You need a
      second snapshot by week 3 to have a real change log.

Explain out loud:
- Why is the raw response saved before anything is parsed?
- What does `content_hash` buy you? What would break without it?
- Why does `run_snapshot` use a single transaction?
- A run returns 40% fewer provisions than last time. What happens, and why is that the right default?
- What is `ON CONFLICT ... DO UPDATE` doing here?

## Week 2 (23 to 29 Nov): measure, then improve

- [ ] **S6. Question set, part 1.** Copy `eval/questions.conc.template.jsonl` to
      `eval/questions.conc.jsonl`. Write 40 questions. Use real situations from the shop.
      Vary the wording: do not reuse the rule's own words, or keyword search wins unfairly.
- [ ] **S7. Question set, part 2.** Reach about 100 answerable and 20 out of scope. Tag each
      with `topic` and `difficulty`.
- [ ] **S8. Retrieval baseline.** `python -m fcaqa eval eval/questions.conc.jsonl
      --sourcebook CONC --retrieval-only --label conc_retrieval`. Record the table. Open the
      JSON, look at `retrieval_misses`, and read ten of them. Why were they missed?
- [ ] **S9. Connect a model** (SETUP step 5) and run the full evaluation.
- [ ] **S10. Tune the refusal threshold.** For each question, record the best similarity.
      Compare answerable against out-of-scope questions and choose `MIN_SIMILARITY`. Hold back
      20 questions you did not tune on and report on those.
- [ ] **S11. One improvement, measured.** Try one change (for example more candidates before
      fusion, or weighting one search above the other) and keep it only if the numbers move.
      A change that did not help is still a result worth writing down.

Explain out loud:
- What do hit@5 and MRR measure, and when would they disagree?
- Why does keyword search OR the words together instead of AND?
- What is an embedding? Why cosine distance?
- How does reciprocal rank fusion work, and why use ranks instead of scores?
- Where can this system still give a wrong answer with a valid citation?
- Why is a held-out set needed for the threshold?

## Week 3 (30 Nov to 6 Dec): ship

- [ ] **S12. Extension.** Pick one and build it yourself:
      - split long provisions into overlapping parts that still cite the parent ID
      - a reranking step on the top 20 candidates
      - a weekly "what changed" digest generated from `provision_changes`
      - a small dashboard over `qa_log`: refusal rate, latency, most-asked topics
- [ ] **S13. Deploy.** A hosted Postgres that supports pgvector plus a hosted Streamlit app.
      Check current free tiers. Put a visible "not legal advice" note and a per-day question
      limit on the public app so a stranger cannot run up your model bill.
- [ ] **S14. README.** Fill in Results and "what I learned". Add a screenshot. Make the
      repository public.
- [ ] **S15. Tell people.** One LinkedIn post, add the project to your CV and Featured section,
      and put the link in your cold emails.

Explain out loud:
- Walk through one request from the text box to the cited answer.
- What happens when the model cites a provision that was not retrieved?
- What would you change to serve 100 users at once?
- What would you do next with another month?

---

## CV bullets to fill in when it is true

- Built a question-answering service over the FCA consumer credit sourcebook (**N** provisions)
  using the official Handbook API, PostgreSQL with pgvector, FastAPI and Docker
- Wrote a **N**-question evaluation set; hybrid search found the correct provision in the top 5
  for **X**% of questions against **Y**% for keyword search alone
- Enforced citations in code: answers without a valid cited provision are refused; **Z**% of
  out-of-scope questions correctly declined
- Tracked rule changes between weekly snapshots with content hashing and data-quality gates
  that roll back partial loads

## Risks

| Risk | What to do |
|---|---|
| API terms restrict what you can show | Show short extracts with a link to the official page. Never commit Handbook text. Ask the FCA if unsure. |
| API shape is awkward | Everything after `fetch_sourcebook` only needs a list of records. Keep the awkwardness in that one function. |
| Model costs | Use a local model while developing. Set a spending cap. Evaluation is the only bulk use. |
| Running out of time | Weeks 1 and 2 are the project. The extension and the deploy can slip a week. The evaluation cannot. |

---

## After this: the gold and silver pipeline

Do it second, not alongside. See `docs/GOLD_PLAN.md`. Start it only when the app above is
deployed, because one finished project beats two half-built ones.
