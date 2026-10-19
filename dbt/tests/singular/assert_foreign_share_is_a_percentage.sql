select
    period,
    security_type,
    foreign_share_pct
from {{ ref('mart_foreign_ownership_monthly') }}
where foreign_share_pct < 0 or foreign_share_pct > 100
