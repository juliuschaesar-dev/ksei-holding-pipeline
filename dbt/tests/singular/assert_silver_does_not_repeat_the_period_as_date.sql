-- depends_on: {{ ref('satellite_master_securities') }}
-- depends_on: {{ ref('satellite_holding_composition') }}
-- The file's Date column always equals the period (assert_bronze_period_matches_the_file_date), so
-- the satellites keep the period as their child key and do not repeat it as a payload column.
select
    table,
    name
from system.columns
where database = 'silver' and name = 'date'
