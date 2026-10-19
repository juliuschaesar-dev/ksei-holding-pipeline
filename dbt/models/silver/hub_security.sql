{# A security, identified by its KSEI code. Both files contribute: about 280 codes appear
   only in the holding file and about 200 only in the master file. #}

{{ dv_hub(
    sources       = [
        {'relation': source('bronze', 'stg_master_securities'), 'record_source': 'bronze.stg_master_securities'},
        {'relation': source('bronze', 'stg_holding_composition'), 'record_source': 'bronze.stg_holding_composition'}
    ],
    hash_key      = 'hmd5_security',
    business_keys = ['code']
) }}
