-- The source total of a residency (local_total or foreign_total) must equal the sum of the
-- investor-type quantities that the fact holds for it. Zero rows are left out of the fact, which
-- does not change the sum.
select
    period,
    security_code,
    residency,
    sum(quantity) as summed,
    min(total_quantity) as source_total
from {{ ref('fact_holding_monthly') }}
group by period, security_code, residency
having sum(quantity) != min(total_quantity) or min(total_quantity) != max(total_quantity)
