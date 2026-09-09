# Runtime Directory Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate Docker-generated local state under `var/` while preserving the project pipeline and its existing local data.

**Architecture:** Docker Compose remains at the repository root, but service bind mounts point to dedicated subdirectories under `var/`. Source modules, Airflow DAGs, dbt project files, and their imports are unchanged. Documentation describes the resulting top-level ownership boundaries.

**Tech Stack:** Docker Compose, Python/pytest, Git, Markdown.

---

### Task 1: Establish a safe runtime-state baseline

**Files:**
- Inspect: `docker-compose.yml`
- Inspect: `.minio_data/`, `.pg_data/`, `.metabase_data/`, `.airflow_metadata/`

- [x] **Step 1: Inspect Git changes and Docker container state**

Run: `git diff -- .gitignore docker-compose.yml && docker compose ps`

Expected: Existing Phase 5 edits are visible and running services, if any, are identified before directory relocation.

- [x] **Step 2: Stop the Compose project without deleting volumes or data**

Run: `docker compose stop`

Expected: Service containers stop; the four host runtime directories remain intact.

### Task 2: Consolidate local runtime state

**Files:**
- Create: `var/.gitkeep`
- Move: `.minio_data/` to `var/minio/`
- Move: `.pg_data/` to `var/postgres/`
- Move: `.metabase_data/` to `var/metabase/`
- Move: `.airflow_metadata/` to `var/airflow/`
- Modify: `.gitignore`
- Modify: `docker-compose.yml`

- [x] **Step 1: Create the ignored directory marker**

Add `var/` to `.gitignore` and add an exception for `var/.gitkeep`; create the empty marker file.

- [x] **Step 2: Move each stopped service directory to its named `var/` location**

Run: `Move-Item -LiteralPath <old-path> -Destination <new-path>` once per exact source directory.

Expected: Each original root directory disappears and each destination exists with the same contents.

- [x] **Step 3: Point Compose to the new host paths**

Replace `.minio_data`, `.pg_data`, `.metabase_data`, and `.airflow_metadata` sources with `./var/minio`, `./var/postgres`, `./var/metabase`, and `./var/airflow` respectively. Preserve container mount destinations and all service settings.

### Task 3: Document the stable project layout

**Files:**
- Create: `docs/structure.md`
- Modify: `README.md`

- [x] **Step 1: Add concise directory ownership documentation**

Describe `src/`, `dags/`, `warehouse/`, `tests/`, `docs/`, and untracked `var/`, including the rule that service state never belongs at the root.

- [x] **Step 2: Update the README structure tree and local runtime note**

Add `dags/`, `docs/`, and `var/` to the documented layout and note that `var/` is generated local state ignored by Git.

### Task 4: Verify the refactor and restore services

**Files:**
- Verify: `.gitignore`, `docker-compose.yml`, `var/.gitkeep`

- [x] **Step 1: Run Python tests**

Run: `python -m pytest`

Expected: All tests pass.

- [x] **Step 2: Validate Compose expansion**

Run: `docker compose config --quiet`

Expected: Exit code 0.

- [ ] **Step 3: Start services using the relocated directories**

Run: `docker compose up -d`

Expected: Containers start or report existing healthy state without creating legacy root runtime directories.

- [x] **Step 4: Confirm Git tracks only the marker, not runtime data**

Run: `git check-ignore -v var/postgres/PG_VERSION; git status --short`

Expected: `var/postgres/PG_VERSION` is ignored; `var/.gitkeep` and intentional source/config/docs changes are visible for staging.
