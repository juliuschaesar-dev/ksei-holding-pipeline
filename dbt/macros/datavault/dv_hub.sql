{#
    Hub loader.

    De-duplicate the business key across every source, hash it, and insert only what is not
    already in the table. A hub is the most stable thing in the warehouse: once a key is here it
    never changes and it is never removed. The load is insert-only, so a re-run is a no-op.

    Args:
        sources:       list of {'relation': source()/ref(), 'record_source': tag}. A key found in
                       several sources is recorded once, against the alphabetically first tag.
        hash_key:      name of the hub's MD5 surrogate key column.
        business_keys: list of natural key columns forming the hub's grain.
#}
{% macro dv_hub(sources, hash_key, business_keys) -%}

{{ config(order_by=hash_key) }}
{% set key_names = [] %}
{% for key in business_keys %}{% do key_names.append(dv_key_name(key)) %}{% endfor %}

with source_rows as (

    {% for source in sources -%}
    select
        {% for key in business_keys -%}
        {{ dv_clean(dv_key_column(key)) }} as `{{ dv_key_name(key) }}_clean`,
        {% endfor -%}
        '{{ source.record_source }}' as record_source
    from {{ source.relation }}
    where {{ dv_not_empty_filter(business_keys) }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}

),

first_seen as (

    select
        {% for key in business_keys -%}
        `{{ dv_key_name(key) }}_clean` as {{ dv_key_name(key) }},
        {% endfor -%}
        min(record_source) as record_source
    from source_rows
    group by {% for key in business_keys %}`{{ dv_key_name(key) }}_clean`{{ ', ' if not loop.last }}{% endfor %}

),

hashed as (

    select
        {{ dv_hash(key_names) }} as {{ hash_key }},
        {% for key in business_keys -%}
        {{ dv_key_name(key) }},
        {% endfor -%}
        {{ dv_load_timestamp() }} as load_timestamp,
        record_source
    from first_seen

)

select * from hashed
{% if is_incremental() -%}
where {{ hash_key }} not in (select {{ hash_key }} from {{ this }})
{%- endif %}

{%- endmacro %}
