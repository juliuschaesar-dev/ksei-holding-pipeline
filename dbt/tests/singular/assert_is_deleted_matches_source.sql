-- is_deleted is a stored mirror of "does this grain still exist in its source", kept true by the
-- dv_track_deletions() post-hook. It can go stale exactly the way a cache can, so recompute the
-- comparison from a fresh read of bronze and assert it agrees (see dv_deleted_flag_problems).
{{ dv_deleted_flag_problems(
    'satellite_master_securities', 'stg_master_securities', 'lmd5_master_securities',
    ['code', 'isin_code', 'currency']
) }}

union all

{{ dv_deleted_flag_problems(
    'satellite_holding_composition', 'stg_holding_composition', 'hmd5_security', ['code']
) }}
