# Architecture Reference — Indonesia Electronics Retail Price Monitor

**Status:** Canonical architecture reference. All future implementation plans
and code must follow this document when an older draft disagrees.

## Data flow

```text
Public product page
        ↓
Python source adapter
(Requests + BeautifulSoup)
        ↓
Raw HTML/JSON response + request metadata + run manifest
        ↓
MinIO Bronze (immutable evidence)
        ↓
Parser + Pydantic validation
        ├── invalid → MinIO rejected (validation reason retained)
        ↓ valid
Parquet Silver (PyArrow; normalized, append-only observations)
        ↓
Python loader
        ↓
PostgreSQL landing
        ↓
dbt staging → intermediate → Gold data marts
        ↓
Metabase
```

## Why this order matters

The raw response is stored in Bronze **before** Pydantic validates the parsed
record. A parser can fail because a website changes its page layout. Retaining
the original HTML/JSON makes that failure debuggable and prevents us from
losing evidence. Pydantic validates the parsed product observation, not the
unmodified web response.

`rejected/` retains the validation result for bad records. It does not replace
the original Bronze object.

Parquet is a file format, so PyArrow is the library that writes and reads the
Silver files. PostgreSQL is not a duplicate Bronze store: it is the query
serving warehouse where dbt builds business-facing models for Metabase.

## Responsibility of each tool

| Tool | Responsibility |
|---|---|
| Requests + BeautifulSoup | Fetch and parse eligible public product pages |
| Pydantic | Validate parsed observation contracts at runtime |
| MinIO | Retain immutable Bronze payloads, manifests, and rejected-record reports |
| PyArrow + Parquet | Create efficient, normalized Silver observation history |
| Python loader | Load Silver rows into PostgreSQL safely and idempotently |
| PostgreSQL | Hold landing tables and the dbt analytical warehouse |
| dbt | Build staging, intermediate, and Gold/data-mart SQL models; run data tests |
| Metabase | Read Gold marts for dashboard and exploration |
| Airflow | Orchestrate the pipeline after each task works independently |
| pytest | Test Python code, parser behavior, contracts, and integration boundaries |
| Docker Compose | Run MinIO, PostgreSQL, Airflow, and Metabase locally |
| GitHub Actions | Run CI: linting, fixture-based pytest, dbt build/tests, and secret scanning |

GitHub Actions is called CD only if a real deployment target is later added.
The initial portfolio scope is CI, not automatic deployment.

## Orchestration flow

Airflow is a control layer, not a place where data is stored. Its daily DAG is:

```text
source policy check
  → collect raw response
  → write Bronze + manifest
  → parse and validate
  → write Silver
  → load PostgreSQL
  → dbt build and dbt tests
  → publish freshness/report status
```

One source may fail without blocking other sources. Airflow is added only in
Phase 5 after every step can be run and tested by itself.

## Source-collection rule

Requests + BeautifulSoup remain the default. Browser automation is not part of
the baseline. If a catalogue page does not expose product links, the run uses a
reviewed product URL basket and reports discovery health explicitly.

## Phase alignment

| Phase | Architecture outcome |
|---|---|
| 1 — Discovery & POC | Prove public product detail extraction and record source limits |
| 2 — Ingestion & Bronze | Persist raw payloads/manifests, validate records, and retain rejected results |
| 3 — Silver & history | Produce normalized, append-only Parquet observations and quality checks |
| 4 — Warehouse & Gold | Load PostgreSQL and build tested dbt marts |
| 5 — Reliability & delivery | Add Airflow, Docker Compose, CI, observability, and Metabase |
