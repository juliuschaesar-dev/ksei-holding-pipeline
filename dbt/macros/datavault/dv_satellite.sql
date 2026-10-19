{#
    Satellite loader.

    Carries the descriptive attributes hanging off a hub or a link. Pick up the parent's business
    keys plus a payload, build md5_diff over (parent keys + child keys + payload), and insert a
    row whenever that hash differs from the version currently in force for the grain.

    Satellites are append-only for data: a changed attribute is a new row, so the full history stays
    recoverable and a re-run cannot alter what is already loaded. Two bookkeeping flags on each row
    are kept current by post-hooks that run after every load:

      meta_is_active  1 for the version in force, 0 once a newer version supersedes it
                      (dv_deactivate_superseded).
      is_deleted      1 on a row inserted when the grain disappeared from the source
                      (dv_track_deletions); a grain that comes back is loaded as a normal new
                      row with is_deleted = 0.

    Comparing against the latest version (not against every version ever loaded) means a payload
    that changes A -> B -> A is recorded as three rows, not two.

    The flags are changed with ClickHouse lightweight UPDATE, which needs the table settings
    enable_block_number_column and enable_block_offset_column (set below).

    Args:
        source_table:         name of the bronze source table (schema is the `bronze` source).
        parent_hash_key:      hub or link MD5 column this satellite hangs off.
        parent_business_keys: natural keys that produce parent_hash_key (see dv_key_name).
        payload:              descriptive columns tracked for change.
        record_source:        lineage tag written to every row.
        child_keys:           extra columns that widen the satellite's grain (a multi-active
                              satellite), for example the reporting period of a snapshot. A column
                              name or {'name': ..., 'column': ...} (see dv_key_name). They take
                              part in md5_diff and in the current-row window.
#}
{% macro dv_satellite(
    source_table,
    parent_hash_key,
    parent_business_keys,
    payload,
    record_source,
    child_keys=[]
) -%}

{% set child_names = [] %}
{% for key in child_keys %}{% do child_names.append(dv_key_name(key)) %}{% endfor %}
{%- set descriptors = child_names + payload -%}
{%- set grain = [parent_hash_key] + child_names -%}
{{ config(
    order_by='(' ~ grain | join(', ') ~ ', load_timestamp)',
    settings={'enable_block_number_column': 1, 'enable_block_offset_column': 1},
    post_hook=[
        "{{ dv_track_deletions('" ~ source_table ~ "', '" ~ parent_hash_key ~ "', "
            ~ parent_business_keys | tojson ~ ", " ~ payload | tojson ~ ", " ~ child_keys | tojson ~ ") }}",
        "{{ dv_deactivate_superseded('" ~ parent_hash_key ~ "', " ~ child_names | tojson ~ ") }}"
    ]
) }}

{% set key_names = [] %}
{% for key in parent_business_keys %}{% do key_names.append(dv_key_name(key)) %}{% endfor %}
{% set clean_names = [] %}
{% for name in key_names %}{% do clean_names.append('`' ~ name ~ '_clean`') %}{% endfor %}

with source_rows as (

    select distinct
        {% for key in parent_business_keys -%}
        {{ dv_clean(dv_key_column(key)) }} as `{{ dv_key_name(key) }}_clean`,
        {% endfor -%}
        {% for key in child_keys -%}
        {{ dv_key_column(key) }} as `{{ dv_key_name(key) }}`,
        {% endfor -%}
        {% for column in payload -%}
        {{ column }}{{ "," if not loop.last }}
        {% endfor -%}
    from {{ source('bronze', source_table) }}
    where {{ dv_not_empty_filter(parent_business_keys) }}

),


hashed as (

    select
        {{ dv_hash(clean_names) }} as {{ parent_hash_key }},
        {{ dv_hash(clean_names + descriptors) }} as md5_diff,
        {% for column in descriptors -%}
        {{ column }},
        {% endfor -%}
        {{ dv_load_timestamp() }} as load_timestamp,
        '{{ record_source }}' as record_source,
        toInt64(1) as meta_is_active,
        toInt64(0) as is_deleted
    from source_rows

)

select * from hashed
{% if is_incremental() -%}
where ({{ grain | join(', ') }}, md5_diff) not in (
    select {{ grain | join(', ') }}, current_diff
    from (
        select
            {{ grain | join(', ') }},
            argMax(md5_diff, tuple(load_timestamp, md5_diff)) as current_diff
        from {{ this }}
        group by {{ grain | join(', ') }}
    )
)
{%- endif %}

{%- endmacro %}


{#
    Live rows of a satellite: the version in force for each grain, unless the grain was deleted at
    the source. meta_is_active and is_deleted are stored on the row (see dv_satellite).

    Args:
        satellite_relation: ref() of the satellite to read.
#}
{% macro dv_satellite_current(satellite_relation) -%}

    select *
    from {{ satellite_relation }}
    where meta_is_active = 1
      and is_deleted = 0

{%- endmacro %}


{#
    Demote every satellite row that a newer version has superseded.

    Runs as a post-hook on each satellite. A row stays active only while it is the latest row of its
    grain by (load_timestamp, md5_diff), the same ordering the loader compares by, so the winner is
    deterministic even when two versions arrive in one load and share a timestamp. A lightweight
    UPDATE touches only the rows that change.

    Args:
        parent_hash_key: the satellite's parent MD5 column.
        child_names:     extra grain columns, matching the dv_satellite call.
#}
{% macro dv_deactivate_superseded(parent_hash_key, child_names=[]) -%}

    {%- set grain = [parent_hash_key] + child_names -%}
    update {{ this }}
    set meta_is_active = 0
    where meta_is_active = 1
      and ({{ grain | join(', ') }}, md5_diff) not in (
          select {{ grain | join(', ') }}, argMax(md5_diff, tuple(load_timestamp, md5_diff))
          from {{ this }}
          group by {{ grain | join(', ') }}
      )

{%- endmacro %}


{#
    Insert a marker row for every grain that is in force but no longer in the source.

    Runs as a post-hook on each satellite, before dv_deactivate_superseded(), so the marker is
    demoted/promoted by the same pass as any other new row. It is an insert, not an update: the row
    being superseded is untouched, and the moment the deletion was noticed becomes its own entry in
    the history. The marker copies the attributes of the row it supersedes, has is_deleted = 1, and a
    derived md5_diff (so a change of state always changes the hash).

    A grain that reappears needs no help here: its payload hash differs from the marker's, so the
    loader inserts it as a normal new row with is_deleted = 0.

    "Present in the source" is a complete answer, not a delta: bronze replaces a whole period when it
    is reloaded, so a row that vanishes from a reloaded period really has left the source.

    Args:
        source_table:         name of the bronze source table.
        parent_hash_key:      the satellite's parent MD5 column.
        parent_business_keys: natural keys that produce parent_hash_key, as in dv_satellite.
        payload:              descriptive columns, matching the dv_satellite call.
        child_keys:           extra grain columns, matching the dv_satellite call.
#}
{% macro dv_track_deletions(source_table, parent_hash_key, parent_business_keys, payload, child_keys=[]) -%}

    {%- set raw_keys = [] -%}
    {%- for key in parent_business_keys -%}
        {%- do raw_keys.append(dv_key_column(key)) -%}
    {%- endfor -%}
    {%- set child_names = [] -%}
    {%- set child_columns = [] -%}
    {%- for key in child_keys -%}
        {%- do child_names.append(dv_key_name(key)) -%}
        {%- do child_columns.append(dv_key_column(key) ~ ' as ' ~ dv_key_name(key)) -%}
    {%- endfor -%}
    {%- set grain = [parent_hash_key] + child_names -%}
    {%- set descriptors = child_names + payload -%}

    insert into {{ this }} (
        {{ parent_hash_key }},
        md5_diff,
        {% for column in descriptors -%}
        {{ column }},
        {% endfor -%}
        load_timestamp,
        record_source,
        meta_is_active,
        is_deleted
    )
    select
        active.{{ parent_hash_key }},
        lower(hex(MD5(concat(active.md5_diff, '|deleted')))) as md5_diff,
        {% for column in descriptors -%}
        active.{{ column }},
        {% endfor -%}
        {{ dv_load_timestamp() }} as load_timestamp,
        active.record_source,
        1 as meta_is_active,
        1 as is_deleted
    from {{ this }} as active
    where active.meta_is_active = 1
      and active.is_deleted = 0
      and ({% for column in grain %}active.{{ column }}{{ ', ' if not loop.last }}{% endfor %}) not in (
          select
              {{ dv_hash(raw_keys) }}{% for column in child_columns %},
              {{ column }}{% endfor %}
          from {{ source('bronze', source_table) }}
          where {{ dv_not_empty_filter(parent_business_keys) }}
      )

{%- endmacro %}
