select
    date::date as date,
    week,
    month,
    quarter,
    year,
    day_of_week,
    weekend_flag::boolean as weekend_flag,
    holiday_flag::boolean as holiday_flag,
    holiday_name
from {{ source('landing', 'calendar') }}
