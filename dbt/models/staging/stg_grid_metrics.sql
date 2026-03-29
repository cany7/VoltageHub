{{ config(
    materialized='incremental',
    incremental_strategy='insert_overwrite',
    partition_by={'field': 'observation_date', 'data_type': 'date'},
    cluster_by=['region', 'metric_name'],
    on_schema_change='fail'
) }}

with raw_batch as (
    select *
    from {{ source('raw', 'eia_grid_batch') }}
    {% if var('batch_date', none) %}
        where batch_date = date(
            '{{ var("batch_date") }}'
        )
    {% endif %}
),

parsed_raw_batch as (
    select
        *,
        coalesce(
            safe.parse_timestamp('%Y-%m-%dT%H:%M:%E*S%Ez', period),
            safe.parse_timestamp('%Y-%m-%dT%H', period),
            safe.parse_timestamp('%Y-%m-%d', period)
        ) as parsed_observation_timestamp
    from raw_batch
),

affected_observation_dates as (
    select distinct date(parsed_observation_timestamp) as observation_date
    from parsed_raw_batch
    where parsed_observation_timestamp is not null
),

canonicalized as (
    select  -- noqa: ST06
        raw_batch_source.respondent as region,
        raw_batch_source.respondent_name as region_name,
        raw_batch_source.parsed_observation_timestamp as observation_timestamp,
        case
            when raw_batch_source.fueltype is not null then 'generation'
            when
                lower(raw_batch_source.type_name) = 'demand'
                or lower(raw_batch_source.type) = 'd'
                then 'demand'
            -- Assumption: keep non-fuel metrics aligned to the upstream label.
            -- This preserves source categories without inventing new ones.
            else lower(
                regexp_replace(
                    raw_batch_source.type_name,
                    r'[^a-zA-Z0-9]+',
                    '_'
                )
            )
        end as metric_name,
        cast(raw_batch_source.value as float64) as metric_value,
        nullif(upper(trim(raw_batch_source.fueltype)), '') as energy_source,
        lower(trim(raw_batch_source.value_units)) as unit,
        cast(
            raw_batch_source._ingestion_timestamp as timestamp
        ) as _ingestion_timestamp
    from parsed_raw_batch as raw_batch_source
    {% if is_incremental() %}
        where date(raw_batch_source.parsed_observation_timestamp) in (
            select affected_observation_dates.observation_date
            from affected_observation_dates
        )
    {% endif %}
),

final as (
    select
        region,
        region_name,
        observation_timestamp,
        date(observation_timestamp) as observation_date,
        metric_name,
        metric_value,
        energy_source,
        unit,
        {{ dbt_utils.generate_surrogate_key([
            'region',
            'observation_timestamp',
            'metric_name',
            'energy_source'
        ]) }} as metric_surrogate_key,
        _ingestion_timestamp
    from canonicalized
)

select *
from final
