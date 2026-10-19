{{ config(severity='warn') }}

-- The two KSEI files do not cover the same codes (about 280 held codes are missing from the
-- master file in the real data), so this warns instead of failing.
select distinct
    f.period,
    f.security_code
from {{ ref('fact_holding_monthly') }} as f
left join {{ ref('fact_security_monthly') }} as d on f.period = d.period and f.security_code = d.security_code
where d.security_code = ''
