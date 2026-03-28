{{ config(
    materialized='table'
) }}

select
    region,
    region_name,
    observation_date,
    energy_source,
    sum(metric_value) as daily_total_generation,
    any_value(unit) as unit
from {{ ref('fct_grid_metrics') }}
where
    metric_name = 'generation'
    and energy_source is not null
group by
    region,
    region_name,
    observation_date,
    energy_source
