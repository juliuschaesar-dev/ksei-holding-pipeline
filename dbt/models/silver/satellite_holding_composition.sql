{#
    Holding composition of a security, exactly as typed in bronze. The file has no ISIN, so this
    hangs off the security hub. The reporting period is a child key: one version history per period.
#}

{{ dv_satellite(
    source_table         = 'stg_holding_composition',
    parent_hash_key      = 'hmd5_security',
    parent_business_keys = ['code'],
    child_keys           = [{'name': 'period', 'column': '_period'}],
    payload              = [
        'type',
        'sec_num',
        'price',
        'local_is',
        'local_cp',
        'local_pf',
        'local_ib',
        'local_id',
        'local_mf',
        'local_sc',
        'local_fd',
        'local_ot',
        'local_total',
        'foreign_is',
        'foreign_cp',
        'foreign_pf',
        'foreign_ib',
        'foreign_id',
        'foreign_mf',
        'foreign_sc',
        'foreign_fd',
        'foreign_ot',
        'foreign_total'
    ],
    record_source        = 'bronze.stg_holding_composition'
) }}
