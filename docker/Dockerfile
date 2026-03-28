FROM apache/airflow:2.9.3-python3.11

RUN pip install --no-cache-dir \
    "dbt-core==1.8.*" \
    "dbt-bigquery==1.8.*" \
    google-cloud-bigquery \
    google-cloud-storage \
    requests
