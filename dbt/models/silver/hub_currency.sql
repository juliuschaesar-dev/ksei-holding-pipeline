{# A currency, identified by its code (IDR, USD). Only the master file carries it. #}

{{ dv_hub(
    sources       = [
        {'relation': source('bronze', 'stg_master_securities'), 'record_source': 'bronze.stg_master_securities'}
    ],
    hash_key      = 'hmd5_currency',
    business_keys = ['currency']
) }}
