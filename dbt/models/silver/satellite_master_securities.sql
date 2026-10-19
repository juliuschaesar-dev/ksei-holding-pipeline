{#
    Master file attributes of a security, ISIN and currency, exactly as typed in bronze. The
    currency is a hub (see the link), so it is not repeated here. The security's description, type
    and issuer are here too: KSEI reformats them over time, so they are versioned per period.

    The file is a monthly snapshot, so the reporting period is a child key (a multi-active
    satellite): every period keeps its own version history. The period is not a hub, because a date
    is not a business entity. Exact duplicate rows collapse through the md5_diff.
#}

{{ dv_satellite(
    source_table         = 'stg_master_securities',
    parent_hash_key      = 'lmd5_master_securities',
    parent_business_keys = ['code', 'isin_code', 'currency'],
    child_keys           = [{'name': 'period', 'column': '_period'}],
    payload              = [
        'description',
        'type',
        'issuer',
        'status',
        'stock_exchange',
        'listing_date',
        'form',
        'eff_date_isin',
        'maturity_date',
        'expire_date',
        'exercise_price',
        'interest',
        'interest_type',
        'interest_freq',
        'nominal_value',
        'num_of_sec',
        'originated_amt',
        'current_amt',
        'total_scripless',
        'local_pct',
        'foreign_pct',
        'total_pct',
        'sector',
        'closing_price'
    ],
    record_source        = 'bronze.stg_master_securities'
) }}
