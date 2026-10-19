-- Rank 1 is the largest holder group of a period; the card of the dashboard reads it. Each period
-- must have exactly one, which also means the ranks do not tie.
select
    period,
    countIf(holder_rank = 1) as top_holders
from {{ ref('mart_investor_type_monthly') }}
group by period
having top_holders != 1
