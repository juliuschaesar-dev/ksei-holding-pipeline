-- The vault must hold everything bronze holds, checked at every level.
--   * Hubs and the link are insert-only: a key that leaves the source stays, so the rule is that
--     every key in bronze exists in the vault (the vault may hold more).
--   * A satellite flags a vanished grain as deleted, so its rows in force (not deleted) must equal
--     the rows in bronze exactly; a lost or doubled row shows up in the count.
select
    'security missing from hub_security' as problem,
    {{ dv_hash(['code']) }} as missing_key
from (
    select code from {{ source('bronze', 'stg_master_securities') }}
    union distinct
    select code from {{ source('bronze', 'stg_holding_composition') }}
)
where missing_key not in (select vault.hmd5_security from {{ ref('hub_security') }} as vault)

union all

select
    'isin missing from hub_isin' as problem,
    {{ dv_hash(['isin_code']) }} as missing_key
from {{ source('bronze', 'stg_master_securities') }}
where missing_key not in (select vault.hmd5_isin from {{ ref('hub_isin') }} as vault)

union all

select
    'currency missing from hub_currency' as problem,
    {{ dv_hash(['currency']) }} as missing_key
from {{ source('bronze', 'stg_master_securities') }}
where missing_key not in (select vault.hmd5_currency from {{ ref('hub_currency') }} as vault)

union all

select
    'code-isin-currency missing from link_master_securities' as problem,
    {{ dv_hash(['code', 'isin_code', 'currency']) }} as missing_key
from {{ source('bronze', 'stg_master_securities') }}
where missing_key not in (select vault.lmd5_master_securities from {{ ref('link_master_securities') }} as vault)

union all

select
    'satellite_holding_composition rows in force differ from bronze' as problem,
    toString(vault_rows) as missing_key
from (
    select
        (select count() from {{ source('bronze', 'stg_holding_composition') }}) as bronze_rows,
        (select count() from ({{ dv_satellite_current(ref('satellite_holding_composition')) }})) as vault_rows
)
where bronze_rows != vault_rows

union all

select
    'satellite_master_securities rows in force differ from bronze' as problem,
    toString(vault_rows) as missing_key
from (
    select
        (
            select uniqExact(trimBoth(code), trimBoth(isin_code), trimBoth(currency), _period)
            from {{ source('bronze', 'stg_master_securities') }}
        ) as bronze_rows,
        (select count() from ({{ dv_satellite_current(ref('satellite_master_securities')) }})) as vault_rows
)
where bronze_rows != vault_rows
