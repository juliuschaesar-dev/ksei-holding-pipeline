-- depends_on: {{ ref('dim_period') }}
-- depends_on: {{ ref('fact_security_monthly') }}
-- depends_on: {{ ref('fact_holding_monthly') }}
-- depends_on: {{ ref('mart_foreign_ownership_monthly') }}
-- depends_on: {{ ref('satellite_master_securities') }}
-- depends_on: {{ ref('satellite_holding_composition') }}
-- Bronze, silver and gold use plain String, Int64, Float64, Date and DateTime only (a column may
-- be Nullable). No LowCardinality, Decimal or unsigned types.
select
    database,
    table,
    name,
    type
from system.columns
where
    database in ('bronze', 'silver', 'gold')
    and (
        type like '%LowCardinality%'
        or type like '%Decimal%'
        or type like '%UInt%'
        or type like '%FixedString%'
    )
