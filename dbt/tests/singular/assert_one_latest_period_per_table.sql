-- is_latest_period marks the rows of the newest period of its table. A table with rows must mark exactly
-- one period, or every chart that filters on it would show nothing or several months at once. An empty
-- table, as on a fresh stack, has nothing to mark.
select
    'fact_holding_monthly' as checked_model,
    uniqExactIf(period, is_latest_period = 1) as latest_periods,
    count() as total_rows
from {{ ref('fact_holding_monthly') }}
having total_rows > 0 and latest_periods != 1

union all

select
    'mart_foreign_ownership_monthly' as checked_model,
    uniqExactIf(period, is_latest_period = 1) as latest_periods,
    count() as total_rows
from {{ ref('mart_foreign_ownership_monthly') }}
having total_rows > 0 and latest_periods != 1

union all

select
    'mart_investor_type_monthly' as checked_model,
    uniqExactIf(period, is_latest_period = 1) as latest_periods,
    count() as total_rows
from {{ ref('mart_investor_type_monthly') }}
having total_rows > 0 and latest_periods != 1
