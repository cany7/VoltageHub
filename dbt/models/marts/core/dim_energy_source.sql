{{ config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key='energy_source',
    on_schema_change='fail'
) }}

select distinct energy_source
from {{ ref('stg_grid_metrics') }}
where energy_source is not null
