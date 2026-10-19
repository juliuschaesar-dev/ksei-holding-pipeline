{% set conditions = ['local_total < 0', 'foreign_total < 0'] %}
{% for residency in ['local', 'foreign'] %}
    {% for investor_type in var('investor_types') %}
        {% do conditions.append(residency ~ '_' ~ investor_type ~ ' < 0') %}
    {% endfor %}
{% endfor %}

-- Quantities are counts, so a negative one is a corrupt value. The fact drops zero quantities by
-- filtering on quantity > 0; this makes sure that filter never hides a negative one.
with current_holding as (

    {{ dv_satellite_current(ref('satellite_holding_composition')) }}

)

select
    hmd5_security,
    period
from current_holding
where {{ conditions | join(' or ') }}
