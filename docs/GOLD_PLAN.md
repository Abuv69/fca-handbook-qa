# Project 2 outline: gold and silver collateral pipeline

Start this after the FCA project is deployed. It exists to show the two things the first
project does not: **dbt** and an **orchestrator**.

## Why it is not just another price pipeline

Price-feed pipelines are the most common portfolio project. What makes this one yours is the
pawnbroking layer: turning a spot price into what a ring is worth as collateral, and showing
how far prices must fall before a loan is worth more than the item securing it.

Use public market data only. Nothing from your employer: no prices, no loan terms, no
customer information.

## Shape

```
price source (daily) ──> raw table ──> dbt staging ──> dbt marts ──> dashboard
                              ▲                              │
                         orchestrator (daily, with backfill and tests)
```

1. **Ingest.** Daily gold and silver prices in GBP plus a 10-year backfill. Loads must be
   safe to re-run: the same day twice gives one row.
2. **Staging (dbt).** Clean types, one row per metal per day, tests for uniqueness, nulls and
   freshness.
3. **Marts (dbt).**
   - `price_per_gram`: by metal and purity (9ct 37.5%, 14ct 58.5%, 18ct 75%, 22ct 91.6%, 24ct 99.9%)
   - `volatility`: 30-day rolling change
   - `collateral_scenarios`: for a loan made on day D at a chosen loan-to-value, the first
     later day the item's metal value fell below the amount lent, if any
4. **Orchestrate.** One daily job: ingest, dbt run, dbt test. A failed test stops the dashboard
   updating.
5. **Serve.** A scrap-value calculator (weight, carat) and a collateral-risk chart.

## Before writing any code

- [ ] Choose a price source and read its terms. Check it has history, GBP, and is allowed for
      a public project. Official benchmark prices are licensed, so check carefully.
- [ ] Decide the warehouse: Postgres again (you will know it by then) or DuckDB.
- [ ] Do the dbt Fundamentals course and one orchestration course from `LEARNING.md`.

## Three weeks

| Week | Outcome |
|---|---|
| 1 | Source chosen, backfill loaded, re-runnable daily ingest, raw table tested |
| 2 | dbt project with staging, three marts, tests and generated docs |
| 3 | Orchestrated daily run, dashboard deployed, README with a lineage diagram |

## What an interviewer will ask

- What makes a load idempotent, and how did you prove yours is?
- What is the difference between a staging model and a mart?
- A dbt test fails at 6am. What happens next?
- How would you backfill one bad week without reloading ten years?
