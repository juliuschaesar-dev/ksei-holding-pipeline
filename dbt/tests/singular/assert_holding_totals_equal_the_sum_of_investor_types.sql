-- local_total and foreign_total must equal the sum of their nine investor types, in the version of
-- every holding row that is currently in force.
with current_holding as (

    {{ dv_satellite_current(ref('satellite_holding_composition')) }}

)

select
    hmd5_security,
    period,
    local_total,
    foreign_total
from current_holding
where
    local_total != local_is + local_cp + local_pf + local_ib + local_id + local_mf + local_sc + local_fd + local_ot
    or foreign_total != foreign_is + foreign_cp + foreign_pf + foreign_ib + foreign_id + foreign_mf + foreign_sc + foreign_fd + foreign_ot
