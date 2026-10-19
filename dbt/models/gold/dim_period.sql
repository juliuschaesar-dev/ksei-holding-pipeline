{#
    The calendar: one row per day, with every column of bronze.stg_period under its own name, read
    straight from bronze. The vault is skipped on purpose: a calendar is reference data loaded once
    from a static file, not a business entity of KSEI.

    The one day the source file gives no ISO week is restored to NULL (bronze stores an empty
    string).
#}

{{ config(order_by='(date_actual)') }}

select
    date_actual,
    date_actual_time,
    day_suffix,
    day_name,
    day_of_week,
    day_of_month,
    day_of_quarter,
    day_of_year,
    week_of_month,
    week_of_year,
    {{ null_if_blank('week_of_year_iso') }} as week_of_year_iso,
    month_actual,
    month_name,
    month_name_abbreviated,
    quarter_actual,
    quarter_name,
    year_actual,
    first_day_of_week,
    last_day_of_week,
    first_day_of_month,
    last_day_of_month,
    first_day_of_quarter,
    last_day_of_quarter,
    first_day_of_year,
    last_day_of_year,
    weekend_flag,
    _source_file,
    _ingested_at
from {{ source('bronze', 'stg_period') }}
