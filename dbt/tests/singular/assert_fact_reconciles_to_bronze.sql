-- The vault must neither lose nor duplicate a holding on the way to the gold fact: per period,
-- local and foreign quantities in the fact add up to the totals in bronze. A fan-out in the link
-- or a collapsed satellite is invisible in row-level tests and obvious in a total.
with bronze as (

    select
        _period as period,
        'local' as residency,
        sum(local_total) as quantity
    from {{ source('bronze', 'stg_holding_composition') }}
    group by _period

    union all

    select
        _period as period,
        'foreign' as residency,
        sum(foreign_total) as quantity
    from {{ source('bronze', 'stg_holding_composition') }}
    group by _period

),

fact as (

    select
        period,
        residency,
        sum(quantity) as quantity
    from {{ ref('fact_holding_monthly') }}
    group by period, residency

)

select
    bronze.period,
    bronze.residency,
    bronze.quantity as bronze_quantity,
    fact.quantity as fact_quantity
from bronze
left join fact on bronze.period = fact.period and bronze.residency = fact.residency
where bronze.quantity != coalesce(fact.quantity, 0)
