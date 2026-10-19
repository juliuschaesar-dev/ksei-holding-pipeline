{#
    Holdings in long form, one row per period, security, local or foreign, and investor type.
    Rows with a zero quantity are left out. The security type is the one the holding file gives
    each security (cleaned like the master type), so every holding has one, also when the security
    is missing from the master file.

    Projected entirely from the vault: the holding satellite's current version per security and
    period, labelled with the code from the security hub. Nothing here re-reads bronze.
#}

{{ config(
    order_by='(residency, investor_type, security_code, period)',
    partition_by='toYYYYMM(period)',
) }}

{#- Unpivot the 18 quantity columns (local/foreign x investor type) into rows; each row also carries
    the source total of its residency (local_total or foreign_total). -#}
{% set entries = [] %}
{% for residency in ['local', 'foreign'] %}
    {% for investor_type in var('investor_types') %}
        {% do entries.append("('" ~ residency ~ "', '" ~ investor_type | upper ~ "', sat." ~ residency ~ '_' ~ investor_type ~ ', sat.' ~ residency ~ '_total)') %}
    {% endfor %}
{% endfor %}

with current_holding as (

    {{ dv_satellite_current(ref('satellite_holding_composition')) }}

),

holdings as (

    select
        sat.period,
        security_hub.code as security_code,
        {{ clean_text('sat.type') }} as security_type,
        sat.sec_num,
        sat.price as source_price,
        arrayJoin([{{ entries | join(', ') }}]) as entry
    from current_holding as sat
    inner join {{ ref('hub_security') }} as security_hub
        on sat.hmd5_security = security_hub.hmd5_security

),

unpivoted as (

    select
        period,
        security_code,
        security_type,
        entry.1 as residency,
        entry.2 as investor_type,
        {{ investor_type_name('entry.2') }} as investor_type_name,
        entry.3 as quantity,
        entry.4 as total_quantity,
        sec_num,
        {{ as_float('source_price', 4) }} as price
    from holdings

)

select
    concat(toString(period), '|', security_code, '|', residency, '|', investor_type) as holding_key,
    period,
    security_code,
    security_type,
    residency,
    investor_type,
    investor_type_name,
    quantity,
    total_quantity,
    sec_num,
    price,
    {{ as_float('quantity * price', 4) }} as holding_value,
    {{ is_latest_period() }} as is_latest_period
from unpivoted
where quantity > 0
