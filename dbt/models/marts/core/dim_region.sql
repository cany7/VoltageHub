{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key='region',
    on_schema_change='fail'
) }}

with ranked_regions as (
    select
        region,
        region_name,
        row_number() over (
            partition by region
            order by _ingestion_timestamp desc, observation_timestamp desc
        ) as region_rank
    from {{ ref('stg_grid_metrics') }}
    where region is not null
)

select
    region,
    region_name
from ranked_regions
where region_rank = 1
