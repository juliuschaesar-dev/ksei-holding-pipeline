{# An instrument, identified by its ISIN. Only the master file carries ISINs. #}

{{ dv_hub(
    sources       = [
        {'relation': source('bronze', 'stg_master_securities'), 'record_source': 'bronze.stg_master_securities'}
    ],
    hash_key      = 'hmd5_isin',
    business_keys = ['isin_code']
) }}
