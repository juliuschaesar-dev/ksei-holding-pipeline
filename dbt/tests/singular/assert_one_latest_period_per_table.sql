-- is_latest_period marks the rows of the newest period of its table. It must mark exactly one period
-- in each table, or every chart that filters on it would show nothing or several months at once.
select
    'fact_holding_monthly' as checked_model,
    uniqExactIf(period, is_latest_period = 1) as latest_periods
from {{ ref('fact_holding_monthly') }}
having latest_periods != 1

union all

select
    'mart_foreign_ownership_monthly' as checked_model,
    uniqExactIf(period, is_latest_period = 1) as latest_periods
from {{ ref('mart_foreign_ownership_monthly') }}
having latest_periods != 1

union all

select
    'mart_investor_type_monthly' as checked_model,
    uniqExactIf(period, is_latest_period = 1) as latest_periods
from {{ ref('mart_investor_type_monthly') }}
having latest_periods != 1
