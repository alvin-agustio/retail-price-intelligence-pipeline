from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

with DAG(
    'erpm_daily_pipeline',
    start_date=datetime(2023, 1, 1),
    schedule='0 2 * * *',
    catchup=False,
    max_active_runs=1,
    max_active_tasks=4,
    default_args={'retries': 1, 'retry_delay': timedelta(minutes=5)}
) as dag:
    
    run_id = "airflow-{{ ts_nodash }}"

    sources = ("erablue", "eraspace", "electronic_city", "digimap")
    categories = ("smartphone", "tablet")
    limit = 5
    load_tasks = []

    for source in sources:
        for category in categories:
            ingest = BashOperator(
                task_id=f"ingest_{source}_{category}",
                bash_command=(
                    f"cd /opt/airflow/project && "
                    f"PYTHONPATH=src python -m retail_pipeline.jobs.ingest "
                    f"--source {source} --category {category} "
                    f"--run-id {run_id} --limit {limit}"
                ),
            )

            build_silver = BashOperator(
                task_id=f"build_silver_{source}_{category}",
                bash_command=(
                    f"cd /opt/airflow/project && "
                    f"PYTHONPATH=src python -m retail_pipeline.jobs.build_silver "
                    f"--source {source} --category {category} "
                    f"--run-id {run_id}"
                ),
            )

            load_landing = BashOperator(
                task_id=f"load_landing_{source}_{category}",
                bash_command=(
                    f"cd /opt/airflow/project && "
                    f"PYTHONPATH=src python -m retail_pipeline.jobs.load_warehouse "
                    f"--source {source} --category {category} "
                    f"--run-id {run_id}"
                ),
            )

            ingest >> build_silver >> load_landing
            load_tasks.append(load_landing)

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command="cd /opt/airflow/project/warehouse && dbt build --profiles-dir .",
    )

    for load_task in load_tasks:
        load_task >> dbt_build
