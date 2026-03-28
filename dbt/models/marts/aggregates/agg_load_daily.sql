{{ config(
    materialized='table'
) }}

select
    region,
    region_name,
    observation_date,
    avg(metric_value) as avg_load,
    min(metric_value) as min_load,
    max(metric_value) as max_load,
    sum(metric_value) as total_load,
    any_value(unit) as unit
from {{ ref('fct_grid_metrics') }}
where metric_name = 'demand'
group by
    region,
    region_name,
    observation_date
