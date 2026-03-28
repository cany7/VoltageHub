{{ config(
    materialized='table'
) }}

with daily_load as (
    select
        observation_date,
        region,
        region_name,
        sum(metric_value) as daily_total_load
    from {{ ref('fct_grid_metrics') }}
    where metric_name = 'demand'
    group by
        observation_date,
        region,
        region_name
)

select
    observation_date,
    region,
    region_name,
    daily_total_load,
    -- Assumption: ties use standard SQL rank() behavior.
    -- Equal daily totals share a rank and skip the next value.
    rank() over (
        partition by observation_date
        order by daily_total_load desc, region asc
    ) as rank
from daily_load
