{{ config(
    materialized='incremental',
    incremental_strategy='insert_overwrite',
    partition_by={'field': 'observation_date', 'data_type': 'date'},
    cluster_by=['region', 'metric_name'],
    on_schema_change='fail'
) }}

with raw_batch as (
    select period
    from {{ source('raw', 'eia_grid_batch') }}
    {% if var('batch_date', none) %}
        where batch_date = date(
            '{{ var("batch_date") }}'
        )
    {% endif %}
),

affected_observation_dates as (
    select distinct date(observation_timestamp) as observation_date
    from (
        select
            coalesce(
                safe.parse_timestamp('%Y-%m-%dT%H:%M:%E*S%Ez', period),
                safe.parse_timestamp('%Y-%m-%dT%H', period),
                safe.parse_timestamp('%Y-%m-%d', period)
            ) as observation_timestamp
        from raw_batch
    )
    where observation_timestamp is not null
),

staged_metrics as (
    select
        staged_metrics_source.metric_surrogate_key,
        staged_metrics_source.region,
        staged_metrics_source.region_name,
        staged_metrics_source.observation_timestamp,
        staged_metrics_source.observation_date,
        staged_metrics_source.metric_name,
        staged_metrics_source.metric_value,
        staged_metrics_source.energy_source,
        staged_metrics_source.unit,
        staged_metrics_source._ingestion_timestamp
    from {{ ref('stg_grid_metrics') }} as staged_metrics_source
    {% if is_incremental() %}
        where staged_metrics_source.observation_date in (
            select affected_observation_dates.observation_date
            from affected_observation_dates
        )
    {% endif %}
)

select *
from staged_metrics
