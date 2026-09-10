# Project structure

The repository root contains only source, orchestration, configuration, tests, and documentation. Generated service data belongs in `var/`; its contents are never committed.

| Path | Responsibility |
| --- | --- |
| `src/retail_pipeline/` | Pipeline package: discovery, storage, and executable jobs. |
| `dags/` | Airflow orchestration for the scheduled end-to-end pipeline. |
| `warehouse/` | dbt project for staging models and analytics marts. |
| `tests/` | pytest coverage grouped into discovery, storage, and jobs. |
| `docs/` | Architecture, structure, and implementation records. |
| `var/` | Ignored local state for Docker services and pytest cache. |

## Local runtime data

Docker Compose mounts the following host directories into services:

| Host directory | Service |
| --- | --- |
| `var/minio/` | MinIO object storage |
| `var/postgres/` | PostgreSQL database files |
| `var/metabase/` | Metabase application database |
| `var/airflow/` | Airflow SQLite metadata |
| `var/pytest/` | pytest cache |

Do not move these directories while Docker is running. To reset a local service, stop the Compose project first and remove only that service's directory under `var/`.

## Python package layout

| Path | Responsibility |
| --- | --- |
| `src/retail_pipeline/discovery.py` | Source routing, fetching, parsing, and data contracts. |
| `src/retail_pipeline/storage/` | MinIO Bronze storage and Parquet Silver storage. |
| `src/retail_pipeline/jobs/` | Command-line pipeline stages for ingestion, Silver build, and PostgreSQL load. |
| `tests/discovery/` | Tests for catalogue discovery and parsing. |
| `tests/storage/` | Tests for MinIO and Parquet helpers. |
| `tests/jobs/` | Tests for executable pipeline stages. |
