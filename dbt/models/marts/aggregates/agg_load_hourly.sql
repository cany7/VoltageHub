{{ config(
    materialized='table'
) }}

select
    region,
    region_name,
    observation_timestamp,
    observation_date,
    metric_value as hourly_load,
    unit
from {{ ref('fct_grid_metrics') }}
where metric_name = 'demand'
