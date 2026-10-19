{#- Rebuilt in full on every run, like the other marts. One row per period and investor type: how much it
    holds, how much of that is foreign, and its rank by value. The card of the largest holder group reads
    rank 1 of the latest period. -#}
{{
    config(
        materialized='table',
        engine='MergeTree()',
        order_by='(period, holder_rank)',
        partition_by=none,
    )
}}

with by_type as (

    select
        period,
        investor_type,
        investor_type_name,
        sum(holding_value) as held,
        sumIf(holding_value, residency = 'foreign') as held_by_foreigners
    from {{ ref('fact_holding_monthly') }}
    group by period, investor_type, investor_type_name

)

select
    period,
    investor_type,
    investor_type_name,
    held as holding_value,
    held_by_foreigners as foreign_value,
    if(
        held = 0,
        null,
        {{ as_float('100 * held_by_foreigners / held', 4) }}
    ) as foreign_share_pct,
    toInt64(row_number() over (partition by period order by held desc, investor_type asc)) as holder_rank,
    {{ is_latest_period() }} as is_latest_period
from by_type
