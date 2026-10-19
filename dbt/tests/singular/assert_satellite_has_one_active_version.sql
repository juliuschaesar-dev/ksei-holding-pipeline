-- meta_is_active is stored, not derived, so its correctness depends on the post-hook running after
-- every load. If dv_deactivate_superseded() is skipped, or its grain drifts from the loader's, a
-- satellite ends up with two rows both claiming to be in force.
--
-- Assert at most one active row per grain, for every satellite.
select
    'satellite_master_securities' as satellite,
    count() as active_versions
from {{ ref('satellite_master_securities') }}
where meta_is_active = 1
group by lmd5_master_securities, period
having count() > 1

union all

select
    'satellite_holding_composition' as satellite,
    count() as active_versions
from {{ ref('satellite_holding_composition') }}
where meta_is_active = 1
group by hmd5_security, period
having count() > 1
