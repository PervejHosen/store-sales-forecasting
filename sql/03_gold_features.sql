-- GOLD: model-ready features. Every feature is either known in advance
-- (calendar, planned promotions, planned openings, store facts) or lagged by at
-- least 42 days, so it is available for any day in a 6-week forecast.

CREATE OR REPLACE TABLE gold_features AS
WITH base AS (
    SELECT d.*, s.store_type, s.assortment, s.competition_distance_m,
           s.competition_open_date, s.in_promo2, s.promo2_start_date, s.promo2_months,
           CASE WHEN d.is_valid_sale THEN ln(d.sales) END AS log_sales
    FROM silver_daily d JOIN silver_stores s USING (store_id)
),
holidays AS (
    SELECT *,
        -- days until the next / since the last state holiday for this store (capped at 15)
        least(15, date_diff('day', sales_date,
              min(CASE WHEN state_holiday <> 'none' THEN sales_date END) OVER (
                  PARTITION BY store_id ORDER BY sales_date
                  ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING))) AS days_to_holiday,
        least(15, date_diff('day',
              max(CASE WHEN state_holiday <> 'none' THEN sales_date END) OVER (
                  PARTITION BY store_id ORDER BY sales_date
                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), sales_date)) AS days_after_holiday,
        -- planned closures longer than a weekend (refurbishments): days until reopening / since reopening
        least(30, date_diff('day', sales_date,
              min(CASE WHEN NOT is_open AND isodow(sales_date) <> 7 THEN sales_date END) OVER (
                  PARTITION BY store_id ORDER BY sales_date
                  ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING))) AS days_to_closure,
        least(30, date_diff('day',
              max(CASE WHEN NOT is_open AND isodow(sales_date) <> 7 THEN sales_date END) OVER (
                  PARTITION BY store_id ORDER BY sales_date
                  ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), sales_date)) AS days_after_closure
    FROM base
),
lagged AS (
    SELECT *,
        -- level and weekday shape as known 6 weeks earlier
        avg(log_sales) OVER (PARTITION BY store_id ORDER BY sales_date
            RANGE BETWEEN INTERVAL 132 DAY PRECEDING AND INTERVAL 42 DAY PRECEDING) AS lvl_90d_lag42,
        avg(log_sales) OVER (PARTITION BY store_id, isodow(sales_date), promo ORDER BY sales_date
            RANGE BETWEEN INTERVAL 132 DAY PRECEDING AND INTERVAL 42 DAY PRECEDING) AS dow_promo_90d_lag42,
        avg(log_sales) OVER (PARTITION BY store_id ORDER BY sales_date
            RANGE BETWEEN INTERVAL 367 DAY PRECEDING AND INTERVAL 361 DAY PRECEDING) AS ly_week_avg,
        max(CASE WHEN is_valid_sale THEN log_sales END) OVER (PARTITION BY store_id ORDER BY sales_date
            RANGE BETWEEN INTERVAL 364 DAY PRECEDING AND INTERVAL 364 DAY PRECEDING) AS lag364
    FROM holidays
)
SELECT
    store_id, sales_date, is_open, is_valid_sale, sales, log_sales, customers,
    isodow(sales_date)                         AS dow,
    day(sales_date)                            AS day_of_month,
    month(sales_date)                          AS month,
    weekofyear(sales_date)                     AS week_of_year,
    dayofyear(sales_date)                      AS day_of_year,
    promo::INT                                 AS promo,
    state_holiday, school_holiday::INT         AS school_holiday,
    days_to_holiday, days_after_holiday, days_to_closure, days_after_closure,
    store_type, assortment,
    coalesce(competition_distance_m, 100000)   AS competition_distance_m,
    CASE WHEN competition_distance_m IS NULL THEN 0
         WHEN competition_open_date IS NULL OR sales_date >= competition_open_date THEN 1 ELSE 0 END
                                               AS competitor_open,
    CASE WHEN competition_open_date IS NOT NULL
         THEN date_diff('month', competition_open_date, sales_date) END AS months_since_competitor,
    (in_promo2 AND sales_date >= promo2_start_date)::INT AS promo2_running,
    (in_promo2 AND sales_date >= promo2_start_date
         AND contains(promo2_months, strftime(sales_date, '%b')))::INT AS promo2_month,
    lvl_90d_lag42, dow_promo_90d_lag42, ly_week_avg, lag364
FROM lagged;
