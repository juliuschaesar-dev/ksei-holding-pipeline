-- A calendar is only useful without holes: between its first and last day there must be exactly
-- one row per day. A gap or a repeated day shows up as a difference between the two counts.
select
    count() as days_in_table,
    dateDiff('day', min(date_actual), max(date_actual)) + 1 as days_between_first_and_last
from {{ ref('dim_period') }}
having days_in_table != days_between_first_and_last
