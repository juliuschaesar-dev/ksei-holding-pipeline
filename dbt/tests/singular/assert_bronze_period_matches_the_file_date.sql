-- _period is set by the pipeline from the release; it must agree with the Date column in the file.
select
    _period,
    date,
    code
from {{ source('bronze', 'stg_holding_composition') }}
where date != _period

union all

select
    _period,
    date,
    code
from {{ source('bronze', 'stg_master_securities') }}
where date != _period
