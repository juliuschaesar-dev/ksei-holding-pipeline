{# A security code, the ISIN it stands for and the currency it is denominated in. KSEI occasionally
   reuses one code for two ISINs, so a code can appear in several rows. Declaration order fixes
   lmd5_master_securities; keep it aligned with satellite_master_securities's
   parent_business_keys. #}

{{ dv_link(
    sources      = [
        {'relation': source('bronze', 'stg_master_securities'), 'record_source': 'bronze.stg_master_securities'}
    ],
    hash_key     = 'lmd5_master_securities',
    foreign_keys = [
        {'hash_key': 'hmd5_security', 'business_key': 'code'},
        {'hash_key': 'hmd5_isin',     'business_key': 'isin_code'},
        {'hash_key': 'hmd5_currency', 'business_key': 'currency'}
    ]
) }}
