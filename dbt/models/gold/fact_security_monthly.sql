{#
    One row per period and security code, projected from the master satellite of the vault: the
    version currently in force for each code-ISIN pair and period, then one row per code and period
    (KSEI occasionally reuses a code for two ISINs and the holding file only has the code, so the
    lowest ISIN is kept).

    This is where the raw vault values are cleaned: text is trimmed and upper-cased, empty cells
    that bronze stored as defaults become NULL, and interest types are unified.
#}

{{ config(order_by='(currency, security_code, period)') }}

with current_master as (

    {{ dv_satellite_current(ref('satellite_master_securities')) }}

),

labelled as (

    select
        sat.*,
        security_hub.code as security_code,
        isin_hub.isin_code,
        currency_hub.currency
    from current_master as sat
    inner join {{ ref('link_master_securities') }} as link
        on sat.lmd5_master_securities = link.lmd5_master_securities
    inner join {{ ref('hub_security') }} as security_hub
        on link.hmd5_security = security_hub.hmd5_security
    inner join {{ ref('hub_isin') }} as isin_hub
        on link.hmd5_isin = isin_hub.hmd5_isin
    inner join {{ ref('hub_currency') }} as currency_hub
        on link.hmd5_currency = currency_hub.hmd5_currency

),

one_per_code as (

    select * from labelled
    order by isin_code
    limit 1 by security_code, period

)

select
    period,
    security_code,
    isin_code,
    description,
    {{ clean_text('type') }} as security_type,
    issuer,
    {{ clean_text('status') }} as status,
    {{ null_if_blank('stock_exchange') }} as stock_exchange,
    {{ clean_text('currency') }} as currency,
    form,
    {{ null_if_blank(clean_text('sector')) }} as sector,
    {{ null_if_epoch('listing_date') }} as listing_date,
    {{ null_if_epoch('maturity_date') }} as maturity_date,
    {{ normalize_interest_type('interest_type') }} as interest_type,
    -- 0 means "no coupon information"; zero-coupon paper is told apart by interest_type
    {{ null_if_zero(as_float('interest', 6)) }} as interest_rate,
    exercise_price,
    nominal_value,
    num_of_sec,
    originated_amt,
    current_amt,
    total_scripless,
    local_pct,
    foreign_pct,
    total_pct,
    closing_price
from one_per_code
