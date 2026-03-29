from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.models import Variable
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

from eia_grid_batch_tasks import (
    check_anomalies,
    extract_grid_batch,
    land_raw_to_gcs,
    load_to_bq_raw,
    record_run_metrics,
    update_pipeline_state,
)

DAG_ID = "eia_grid_batch"
DBT_PROJECT_DIR = "/opt/airflow/dbt"


def _resolve_schedule() -> str:
    # Assumption: the schedule is configured through an Airflow Variable so we can
    # keep the SPEC default (`@hourly`) while allowing environment-specific overrides.
    return Variable.get("pipeline_schedule", default_var="@hourly")


def _resolve_start_date() -> pendulum.DateTime:
    configured_start_date = Variable.get("pipeline_start_date", default_var=None)
    if configured_start_date:
        return pendulum.parse(configured_start_date).in_timezone("UTC")

    backfill_days = int(os.environ.get("BACKFILL_DAYS", "7"))
    return pendulum.now("UTC").subtract(days=backfill_days).start_of("hour")


with DAG(
    dag_id=DAG_ID,
    schedule=_resolve_schedule(),
    start_date=_resolve_start_date(),
    catchup=True,
    max_active_runs=1,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
    },
    dagrun_timeout=timedelta(hours=2),
    render_template_as_native_obj=True,
    tags=["voltage-hub", "eia", "batch"],
) as dag:
    extract_task = PythonOperator(
        task_id="extract_grid_batch",
        python_callable=extract_grid_batch,
        op_kwargs={
            "data_interval_start": "{{ data_interval_start }}",
            "data_interval_end": "{{ data_interval_end }}",
        },
        execution_timeout=timedelta(minutes=10),
    )

    land_task = PythonOperator(
        task_id="land_raw_to_gcs",
        python_callable=land_raw_to_gcs,
        op_kwargs={
            "raw_payload": "{{ ti.xcom_pull(task_ids='extract_grid_batch') }}",
        },
        execution_timeout=timedelta(minutes=10),
    )

    load_task = PythonOperator(
        task_id="load_to_bq_raw",
        python_callable=load_to_bq_raw,
        op_kwargs={
            "gcs_uri": "{{ ti.xcom_pull(task_ids='land_raw_to_gcs') }}",
            "raw_payload": "{{ ti.xcom_pull(task_ids='extract_grid_batch') }}",
        },
        execution_timeout=timedelta(minutes=15),
    )

    dbt_source_freshness_task = BashOperator(
        task_id="dbt_source_freshness",
        bash_command=(
            "dbt deps --project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt "
            "&& dbt source freshness --project-dir /opt/airflow/dbt "
            "--profiles-dir /opt/airflow/dbt --target dev"
        ),
        execution_timeout=timedelta(minutes=5),
    )

    dbt_build_task = BashOperator(
        task_id="dbt_build",
        bash_command=(
            "dbt deps --project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt "
            "&& dbt build --project-dir /opt/airflow/dbt --profiles-dir /opt/airflow/dbt "
            "--target dev --vars '{\"batch_date\": \"{{ data_interval_start | ds }}\"}'"
        ),
        execution_timeout=timedelta(minutes=30),
    )

    check_anomalies_task = PythonOperator(
        task_id="check_anomalies",
        python_callable=check_anomalies,
        execution_timeout=timedelta(minutes=5),
    )

    record_run_metrics_task = PythonOperator(
        task_id="record_run_metrics",
        python_callable=record_run_metrics,
        trigger_rule=TriggerRule.ALL_DONE,
        execution_timeout=timedelta(minutes=5),
    )

    update_pipeline_state_task = PythonOperator(
        task_id="update_pipeline_state",
        python_callable=update_pipeline_state,
        execution_timeout=timedelta(minutes=5),
    )

    (
        extract_task
        >> land_task
        >> load_task
        >> dbt_source_freshness_task
        >> dbt_build_task
        >> check_anomalies_task
    )
    check_anomalies_task >> record_run_metrics_task
    check_anomalies_task >> update_pipeline_state_task
