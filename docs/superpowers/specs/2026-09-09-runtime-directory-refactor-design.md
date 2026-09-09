# Runtime Directory Refactor Design

## Goal

Make the repository root easier to scan without changing Python module structure or pipeline behaviour.

## Scope

- Create a single ignored `var/` directory for local service state.
- Move existing Docker runtime directories into `var/`:
  - `.minio_data` → `var/minio`
  - `.pg_data` → `var/postgres`
  - `.metabase_data` → `var/metabase`
  - `.airflow_metadata` → `var/airflow`
- Update Docker Compose volume sources to the new locations.
- Replace the individual runtime ignore rules with `var/` in `.gitignore`.
- Add `var/.gitkeep` so the intended local layout is discoverable while its contents remain untracked.
- Add a short `docs/structure.md` explaining the source, orchestration, dbt, test, and local-runtime directories.
- Update the README project tree and local-run notes to match.

## Explicitly Out of Scope

- No split, rename, or behavioural change in Python modules under `src/`.
- No relocation of `dags/`, `warehouse/`, `docker-compose.yml`, or `Dockerfile.airflow`; they remain in conventional, directly discoverable locations.
- No change to data schemas, container images, services, or environment-variable names.

## Design

`var/` is the single home for disposable local state produced by Docker services. The project root stays focused on source, tests, orchestration, dbt, and project configuration. Docker Compose continues to be run from the repository root; only its bind-mount source paths change.

Before moving the existing state, Docker containers must be stopped so PostgreSQL, MinIO, Metabase, and Airflow cannot write into a directory during the move. The resulting Compose configuration mounts the same data into the same container destinations, preserving service behaviour and local state.

## Validation

1. Run the Python test suite.
2. Validate the expanded Docker Compose configuration.
3. Start the local services and confirm their containers become healthy or running.
4. Confirm Git ignores contents of `var/` while retaining `var/.gitkeep`.
