{#
    Rows where a satellite's stored is_deleted flag disagrees with a fresh read of its source.
    Recomputes the comparison dv_track_deletions() makes:
      * an active, not-deleted row must exist in the source;
      * an active, deleted row must be absent from the source;
      * every grain in the source must have an active row.

    Args:
        satellite_name: name of the satellite model.
        source_table:   name of the bronze source table it is loaded from.
        hash_key:       the satellite's parent MD5 column.
        business_keys:  natural keys that produce hash_key (raw bronze column names).
#}
{% macro dv_deleted_flag_problems(satellite_name, source_table, hash_key, business_keys) -%}

    select * from (

    with source_grain as (

        select distinct
            {{ dv_hash(business_keys) }} as grain_hash,
            _period as period
        from {{ source('bronze', source_table) }}

    )

    select
        '{{ satellite_name }} deleted-but-present' as problem,
        {{ hash_key }} as grain_hash,
        period
    from {{ ref(satellite_name) }}
    where
        meta_is_active = 1
        and is_deleted = 1
        and (grain_hash, period) in (select grain_hash, period from source_grain)

    union all

    select
        '{{ satellite_name }} not-deleted-but-missing' as problem,
        {{ hash_key }} as grain_hash,
        period
    from {{ ref(satellite_name) }}
    where
        meta_is_active = 1
        and is_deleted = 0
        and (grain_hash, period) not in (select grain_hash, period from source_grain)

    union all

    select
        '{{ satellite_name }} source-without-active-row' as problem,
        grain_hash,
        period
    from source_grain
    where (grain_hash, period) not in (
        select {{ hash_key }}, period from {{ ref(satellite_name) }} where meta_is_active = 1
    )

    )

{%- endmacro %}
