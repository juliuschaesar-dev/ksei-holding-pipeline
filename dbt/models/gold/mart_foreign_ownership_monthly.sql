{#- Rebuilt in full on every run: the month-over-month columns need the whole history. -#}
{{
    config(
        materialized='table',
        engine='MergeTree()',
        order_by='(security_type, period)',
        partition_by=none,
    )
}}

-- The security type is the one the holding file gives; the master file only tells the currency.
-- USING joins make the unqualified columns below unambiguous (and keep their plain names in ClickHouse)
-- noqa: disable=RF02
with master_currency as (

    select
        period,
        security_code,
        currency
    from {{ ref('fact_security_monthly') }}

),

holdings as (

    select
        period,
        residency,
        holding_value,
        security_type
    from {{ ref('fact_holding_monthly') }}
    left join master_currency using (period, security_code)
    -- a security missing from the master file has no currency (the join gives ''); assume IDR
    where coalesce(nullIf(currency, ''), 'IDR') = 'IDR'

),
-- noqa: enable=RF02

by_type as (

    select
        period,
        security_type,
        sumIf(holding_value, residency = 'local') as local_value,
        sumIf(holding_value, residency = 'foreign') as foreign_value
    from holdings
    group by period, security_type

),

shares as (

    select
        period,
        security_type,
        local_value,
        foreign_value,
        local_value + foreign_value as total_value,
        if(
            local_value + foreign_value = 0,
            null,
            {{ as_float('100 * foreign_value / (local_value + foreign_value)', 4) }}
        ) as foreign_share_pct
    from by_type

)

select
    period,
    security_type,
    local_value,
    foreign_value,
    total_value,
    foreign_share_pct,
    lagInFrame(toNullable(period), 1) over previous as previous_period,
    {{ as_float('foreign_value - lagInFrame(toNullable(foreign_value), 1) over previous', 4) }} as foreign_value_change,
    {{ as_float('foreign_share_pct - lagInFrame(foreign_share_pct, 1) over previous', 4) }} as foreign_share_change_pp,
    {{ is_latest_period() }} as is_latest_period
from shares
window previous as (
    partition by security_type
    order by period
    rows between unbounded preceding and unbounded following
)
