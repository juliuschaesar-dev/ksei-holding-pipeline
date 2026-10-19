-- The mart groups holdings by the security type of the holding file. That type is what replaced a
-- placeholder for securities missing from the master file, so a row without one would put value in
-- a nameless group.
select
    period,
    security_code
from {{ ref('fact_holding_monthly') }}
where security_type = ''
