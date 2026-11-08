-- GOLD: tables behind the insight charts (open days with valid sales only)

-- Average sales by weekday, with and without promotion
CREATE OR REPLACE TABLE gold_weekday AS
SELECT dow, promo, round(avg(sales)) AS avg_sales, count(*) AS store_days
FROM gold_features WHERE is_valid_sale
GROUP BY dow, promo ORDER BY dow, promo;

-- Promotion lift, like for like: same store, same weekday, same month
CREATE OR REPLACE TABLE gold_promo_lift AS
WITH cells AS (
    SELECT store_id, store_type, dow, month, year(sales_date) AS yr,
           avg(CASE WHEN promo = 1 THEN sales END) AS with_promo,
           avg(CASE WHEN promo = 0 THEN sales END) AS without_promo,
           avg(CASE WHEN promo = 1 THEN customers END) AS cust_promo,
           avg(CASE WHEN promo = 0 THEN customers END) AS cust_no_promo
    FROM gold_features WHERE is_valid_sale AND dow <= 5
    GROUP BY store_id, store_type, dow, month, yr
)
SELECT store_type,
       round(100 * (exp(avg(ln(with_promo / without_promo))) - 1), 1) AS sales_lift_pct,
       round(100 * (exp(avg(ln(cust_promo / cust_no_promo))) - 1), 1) AS customer_lift_pct,
       count(*) AS comparisons
FROM cells WHERE with_promo IS NOT NULL AND without_promo IS NOT NULL
GROUP BY ROLLUP (store_type) ORDER BY store_type NULLS FIRST;

-- School holiday effect, like for like (same store, weekday, month, promo status)
CREATE OR REPLACE TABLE gold_school_holiday AS
WITH cells AS (
    SELECT store_id, dow, month, year(sales_date) AS yr, promo,
           avg(CASE WHEN school_holiday = 1 THEN sales END) AS on_holiday,
           avg(CASE WHEN school_holiday = 0 THEN sales END) AS off_holiday
    FROM gold_features WHERE is_valid_sale AND dow <= 6
    GROUP BY ALL
)
SELECT round(100 * (exp(avg(ln(on_holiday / off_holiday))) - 1), 1) AS lift_pct, count(*) AS comparisons
FROM cells WHERE on_holiday IS NOT NULL AND off_holiday IS NOT NULL;

-- Weekly chain sales (stores with a full history, so the 2014 data gap doesn't distort the line)
CREATE OR REPLACE TABLE gold_weekly AS
SELECT date_trunc('week', sales_date) AS week_start,
       round(sum(sales)) AS sales, count(DISTINCT store_id) AS stores
FROM gold_features
WHERE store_id IN (SELECT store_id FROM silver_daily GROUP BY 1 HAVING count(*) >= 941)
GROUP BY 1 HAVING count(DISTINCT sales_date) = 7 ORDER BY 1;

-- What happens when a competitor opens nearby. Each store's daily sales are compared with the
-- rest of the chain on the same day (removes seasonality, promotions and holidays), then indexed
-- to the 8 weeks before the competitor opened. Periods are 4 weeks long.
CREATE OR REPLACE TABLE gold_competitor_event AS
WITH events AS (
    SELECT store_id, competition_open_date AS open_date
    FROM silver_stores
    WHERE competition_open_date BETWEEN DATE '2013-07-01' AND DATE '2015-01-01'
),
chain AS (
    SELECT sales_date, avg(log_sales) AS chain_log
    FROM gold_features
    WHERE is_valid_sale AND store_id NOT IN (SELECT store_id FROM events)
    GROUP BY sales_date
),
rel AS (
    SELECT e.store_id,
           floor(date_diff('day', e.open_date, f.sales_date) / 28)::INT AS period,
           f.log_sales - c.chain_log AS rel_log
    FROM events e
    JOIN gold_features f USING (store_id)
    JOIN chain c USING (sales_date)
    WHERE f.is_valid_sale
      AND f.sales_date >= e.open_date - INTERVAL 56 DAY
      AND f.sales_date <  e.open_date + INTERVAL 196 DAY
),
per_store AS (
    SELECT store_id, period, avg(rel_log) AS rel_log FROM rel GROUP BY store_id, period
),
pre AS (
    SELECT store_id, avg(rel_log) AS pre_log FROM per_store WHERE period < 0 GROUP BY store_id
)
SELECT period,
       round(100 * exp(avg(rel_log - pre_log)), 1) AS index_vs_before,
       count(*) AS stores
FROM per_store JOIN pre USING (store_id)
GROUP BY period ORDER BY period;

-- Store formats
CREATE OR REPLACE TABLE gold_store_types AS
SELECT store_type, count(DISTINCT store_id) AS stores,
       round(avg(sales)) AS avg_daily_sales, round(avg(customers)) AS avg_customers,
       round(avg(sales / customers), 2) AS avg_basket
FROM gold_features WHERE is_valid_sale GROUP BY 1 ORDER BY 1;
