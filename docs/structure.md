# Project structure

The repository root contains only source, orchestration, configuration, tests, and documentation. Generated service data belongs in `var/`; its contents are never committed.

| Path | Responsibility |
| --- | --- |
| `src/` | Pipeline scripts: ingest Bronze data, build Silver data, and load PostgreSQL. |
| `dags/` | Airflow orchestration for the scheduled end-to-end pipeline. |
| `warehouse/` | dbt project for staging models and analytics marts. |
| `tests/` | pytest coverage for pipeline behaviour. |
| `docs/` | Architecture, structure, and implementation records. |
| `var/` | Ignored local state for MinIO, PostgreSQL, Metabase, and Airflow. |

## Local runtime data

Docker Compose mounts the following host directories into services:

| Host directory | Service |
| --- | --- |
| `var/minio/` | MinIO object storage |
| `var/postgres/` | PostgreSQL database files |
| `var/metabase/` | Metabase application database |
| `var/airflow/` | Airflow SQLite metadata |

Do not move these directories while Docker is running. To reset a local service, stop the Compose project first and remove only that service's directory under `var/`.
