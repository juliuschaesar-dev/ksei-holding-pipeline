{#- Shared cleaning rules. Bronze stores empty cells as '' / 0 / 1970-01-01 (plain types cannot
    hold NULL); silver restores NULL where that carries meaning. -#}

{% macro clean_text(column) -%}
    upperUTF8(trimBoth({{ column }}))
{%- endmacro %}

{% macro null_if_blank(column) -%}
    nullIf(trimBoth({{ column }}), '')
{%- endmacro %}

{% macro null_if_epoch(column) -%}
    nullIf({{ column }}, toDate('1970-01-01'))
{%- endmacro %}

{% macro null_if_zero(column) -%}
    nullIf({{ column }}, 0)
{%- endmacro %}

{#- Amounts and rates are Float64 in bronze; round them to the precision the source carries. -#}
{% macro as_float(column, scale) -%}
    round({{ column }}, {{ scale }})
{%- endmacro %}

{#- KSEI spells the same interest type several ways (FIXED/Fixed, FLOATING/Floating/Variable,
    Zero/Discounted/ZERO RATE / DISCOUNTED). Unknown spellings pass through upper-cased so the
    accepted_values test flags them. -#}
{% macro normalize_interest_type(column) -%}
    multiIf(
        trimBoth({{ column }}) = '', NULL,
        positionCaseInsensitive({{ column }}, 'fix') > 0, 'FIXED',
        positionCaseInsensitive({{ column }}, 'float') > 0, 'FLOATING',
        positionCaseInsensitive({{ column }}, 'zero') > 0, 'ZERO_COUPON',
        {{ clean_text(column) }}
    )
{%- endmacro %}

{#- The name an investor-type code is shown with, from the investor_types var. A code that is not in the
    var passes through as it is, so the accepted_values test flags it. -#}
{% macro investor_type_name(column) -%}
    multiIf(
    {%- for code in var('investor_types') %}
        {{ column }} = '{{ code | upper }}', '{{ var('investor_types')[code] }}',
    {%- endfor %}
        {{ column }}
    )
{%- endmacro %}

{#- 1 on the rows of the newest period of the model, 0 on the others: charts that show "the latest
    period" filter on it instead of each repeating a subquery. -#}
{% macro is_latest_period() -%}
    toInt64(period = max(period) over ())
{%- endmacro %}
