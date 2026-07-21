{{ config(materialized='table') }}

-- Grain: one row per calendar date. date_sk is an integer YYYYMMDD surrogate
-- key (the conventional date-dimension key), so fact tables can join/filter
-- on a cheap integer instead of a date, and can carry a sentinel "unknown
-- date" key (00000000) if ever needed.
select
    (to_char(date, 'YYYYMMDD'))::int as date_sk,
    date,
    week,
    month,
    quarter,
    year,
    day_of_week,
    weekend_flag,
    holiday_flag,
    holiday_name
from {{ ref('stg_calendar') }}
