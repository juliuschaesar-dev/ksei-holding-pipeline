{#
    Hashing primitives shared by every Data Vault 2.0 structure.

    Hub and link keys are MD5 over the business key; satellites hash their payload the same way
    to detect change. This is the single place that behaviour lives.

    A business key is either a column name ('code') or {'name': 'period', 'column': '_period'}
    when the vault column should be called something other than the bronze column.
#}

{% macro dv_key_name(key) -%}
    {{ key.name if key is mapping else key }}
{%- endmacro %}

{% macro dv_key_column(key) -%}
    {{ key.column if key is mapping else key }}
{%- endmacro %}

{#- Normalise a column before hashing it: cast to text, strip whitespace. -#}
{% macro dv_clean(column) -%}
    trimBoth(toString({{ column }}))
{%- endmacro %}

{#- NULL-safe hash input: a NULL or empty value must not collapse onto a real value. -#}
{% macro dv_hash_part(column) -%}
    coalesce(nullIf({{ dv_clean(column) }}, ''), '{{ var("dv_null_placeholder") }}')
{%- endmacro %}

{#-
    MD5 (lower-case hex) over one or more columns. Parts are joined with var('dv_hash_delimiter')
    so that ('AB', 'C') and ('A', 'BC') cannot collide.
-#}
{% macro dv_hash(columns) -%}
    {%- set column_list = [columns] if columns is string else columns -%}
    lower(hex(MD5(
        {%- for column in column_list %}
        {{ dv_hash_part(column) }}
        {%- if not loop.last %} || '{{ var("dv_hash_delimiter") }}' || {% endif %}
        {%- endfor %}
    )))
{%- endmacro %}

{#- Load audit timestamp, in the reporting timezone. -#}
{% macro dv_load_timestamp() -%}
    toTimeZone(now64(3), '{{ var("dv_timezone") }}')
{%- endmacro %}

{#- "a is not empty and b is not empty" for the raw bronze columns behind a list of keys. -#}
{% macro dv_not_empty_filter(keys) -%}
    {%- for key in keys -%}
        {{ dv_clean(dv_key_column(key)) }} != ''
        {%- if not loop.last %} and {% endif -%}
    {%- endfor -%}
{%- endmacro %}
