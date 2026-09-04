# Retail Price Intelligence Pipeline

Project data engineering untuk memantau observasi harga produk elektronik dari beberapa retailer Indonesia. Tujuannya adalah membangun pipeline yang menyimpan data mentah, menormalkan data, lalu menyajikannya sebagai tabel analitik yang siap dipakai dashboard.

## Current status

Phase 1 sampai 4 selesai: discovery produk, Bronze, Silver, PostgreSQL landing, dan dbt Gold marts sudah berjalan serta memiliki automated tests. Phase 5 akan menambahkan orchestration, CI, dan visualisasi.

## Data flow

```text
Public product page
  -> Python extraction
  -> MinIO Bronze (raw HTML, manifest, rejected records)
  -> Parquet Silver (validated observations)
  -> PostgreSQL landing
  -> dbt staging and Gold marts
  -> Metabase (Phase 5)
```

## Current stack

- Python, Requests, BeautifulSoup, and Pydantic
- MinIO for Bronze and Parquet for Silver
- PostgreSQL for the analytical warehouse
- dbt Core with PostgreSQL adapter for data marts and data tests
- pytest for Python tests
- Docker Compose for local MinIO and PostgreSQL

## Main warehouse tables

- `dim_products`: latest known product details per retailer product.
- `fct_prices`: append-only price observations over time.

## Run locally

Use the Anaconda Python environment configured for this project.

```powershell
docker compose up -d
python -m pytest
dbt build --project-dir warehouse --profiles-dir warehouse
```

The current Docker Compose setup starts MinIO and PostgreSQL. Airflow and Metabase are planned for Phase 5.

## Project structure

```text
src/        Python pipeline stages
tests/      pytest coverage for pipeline behaviour
warehouse/  dbt project, staging model, and Gold marts
docs/       architecture reference
```
