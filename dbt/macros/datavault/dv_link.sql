{#
    Link loader.

    Records that a set of business keys occurred together. The link's own MD5 is taken over the
    concatenated keys in declaration order, and each hub's MD5 is re-derived from its own business
    key, so a link never needs to join back to the hubs it references and everything can load in
    parallel. Insert-only: a re-run is a no-op.

    Args:
        sources:      list of {'relation': source()/ref(), 'record_source': tag}.
        hash_key:     name of the link's MD5 surrogate key column.
        foreign_keys: ordered list of {'hash_key': ..., 'business_key': ...}. The order defines
                      the link hash, so it must stay stable. A business key is a column name or
                      {'name': ..., 'column': ...} (see dv_key_name).
#}
{% macro dv_link(sources, hash_key, foreign_keys) -%}

{{ config(order_by=hash_key) }}
{% set business_keys = foreign_keys | map(attribute='business_key') | list %}
{% set key_names = [] %}
{% for key in business_keys %}{% do key_names.append(dv_key_name(key)) %}{% endfor %}

with source_rows as (

    {% for source in sources -%}
    select distinct
        {% for key in business_keys -%}
        {{ dv_clean(dv_key_column(key)) }} as `{{ dv_key_name(key) }}`{{ "," if not loop.last }}
        {% endfor -%}
    from {{ source.relation }}
    where {{ dv_not_empty_filter(business_keys) }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}

),

first_seen as (

    select distinct *
    from source_rows

),

hashed as (

    select
        {{ dv_hash(key_names) }} as {{ hash_key }},
        {% for foreign_key in foreign_keys -%}
        {{ dv_hash(dv_key_name(foreign_key.business_key)) }} as {{ foreign_key.hash_key }},
        {% endfor -%}
        {{ dv_load_timestamp() }} as load_timestamp,
        '{{ sources | map(attribute="record_source") | sort | join(",") }}' as record_source
    from first_seen

)

select * from hashed
{% if is_incremental() -%}
where {{ hash_key }} not in (select {{ hash_key }} from {{ this }})
{%- endif %}

{%- endmacro %}
