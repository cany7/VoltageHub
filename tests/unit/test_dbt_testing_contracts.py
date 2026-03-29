from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_staging_schema_declares_required_23_quality_gates() -> None:
    staging_schema = _read("dbt/models/staging/schema.yml")

    for required_snippet in (
        "- not_null\n          - unique",
        "- name: region\n        description: Standardized balancing area code sourced from the respondent identifier.\n        data_tests:\n          - not_null",
        "- name: observation_timestamp\n        description: Parsed timestamp for the observed grid metric.\n        data_tests:\n          - not_null",
        "- name: metric_name\n        description: Standardized metric category used by downstream marts.\n        data_tests:\n          - not_null\n          - accepted_values:",
        '- name: metric_value\n        description: Numeric metric value as reported by the source.\n        data_tests:\n          - not_null',
        '"BAT"',
        '"BIO"',
        '"HPS"',
        '"HYC"',
        '"WND"',
    ):
        assert required_snippet in staging_schema


def test_marts_schema_declares_relationship_and_grain_tests() -> None:
    marts_schema = _read("dbt/models/marts/core/schema.yml")

    for required_snippet in (
        "dbt_utils.unique_combination_of_columns",
        "- region\n            - observation_timestamp\n            - metric_name\n            - energy_source",
        "to: ref('dim_region')",
        "to: ref('dim_energy_source')",
    ):
        assert required_snippet in marts_schema


def test_source_freshness_contract_declares_warn_and_error_thresholds() -> None:
    sources_yml = _read("dbt/models/sources.yml")

    for required_snippet in (
        "loaded_at_field: _ingestion_timestamp",
        "warn_after:",
        "count: 6",
        "period: hour",
        "error_after:",
        "count: 12",
    ):
        assert required_snippet in sources_yml


def test_sample_mode_dbt_contract_routes_sources_and_schemas_to_sample_datasets() -> None:
    sources_yml = _read("dbt/models/sources.yml")
    meta_schema = _read("dbt/models/meta/schema.yml")
    dbt_project = _read("dbt/dbt_project.yml")
    profiles_yml = _read("dbt/profiles.yml")

    for required_snippet in (
        "BQ_DATASET_RAW_SAMPLE",
        "target.name == 'sample'",
        "BQ_DATASET_META_SAMPLE",
        "BQ_DATASET_STAGING_SAMPLE",
        "BQ_DATASET_MARTS_SAMPLE",
        "sample:\n      type: bigquery",
    ):
        assert (
            required_snippet in sources_yml
            or required_snippet in meta_schema
            or required_snippet in dbt_project
            or required_snippet in profiles_yml
        )


def test_dag_contract_uses_sample_aware_dbt_target_resolution() -> None:
    dag_source = _read("airflow/dags/eia_grid_batch.py")

    assert "resolve_dbt_target" in dag_source
    assert "sample_mode_enabled" in dag_source
    assert "--target {_dbt_target()}" in dag_source
