from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

with DAG(
    'erpm_daily_pipeline',
    start_date=datetime(2023, 1, 1),
    schedule='0 2 * * *',
    catchup=False,
    max_active_runs=1,
    default_args={'retries': 1, 'retry_delay': timedelta(minutes=5)}
) as dag:
    
    run_id = "airflow-{{ ts_nodash }}"
    source = "erablue"
    category = "smartphone" # Kita pake smartphone sebagai automation sample

    # 1. Scraping dari Internet ke MinIO (Bronze)
    ingest = BashOperator(
        task_id='ingest_bronze',
        bash_command=f'cd /opt/airflow/project && python src/run_ingestion.py --source {source} --category {category} --run-id {run_id}'
    )

    # 2. Extract & Clean ke format Parquet (Silver)
    build_silver = BashOperator(
        task_id='build_silver',
        bash_command=f'cd /opt/airflow/project && python src/build_silver.py --source {source} --category {category} --run-id {run_id}'
    )

    # 3. Load ke PostgreSQL (Landing)
    load_warehouse = BashOperator(
        task_id='load_landing',
        bash_command=f'cd /opt/airflow/project && python src/load_warehouse.py --source {source} --category {category} --run-id {run_id}'
    )

    # 4. Transform dengan dbt (Marts / Gold)
    dbt_build = BashOperator(
        task_id='dbt_build',
        bash_command='cd /opt/airflow/project/warehouse && dbt build --profiles-dir .'
    )

    ingest >> build_silver >> load_warehouse >> dbt_build
