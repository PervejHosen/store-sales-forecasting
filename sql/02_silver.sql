-- SILVER: typed, cleaned, one row per store and day

CREATE OR REPLACE TABLE silver_stores AS
SELECT
    Store                                   AS store_id,
    StoreType                               AS store_type,
    Assortment                              AS assortment,
    CompetitionDistance                     AS competition_distance_m,
    CASE WHEN CompetitionOpenSinceYear IS NOT NULL
         THEN make_date(CompetitionOpenSinceYear::INT, CompetitionOpenSinceMonth::INT, 1) END
                                            AS competition_open_date,
    Promo2 = 1                              AS in_promo2,
    -- Promo2 starts on the Monday of the given ISO week
    CASE WHEN Promo2 = 1 THEN
         make_date(Promo2SinceYear::INT, 1, 4)
         - INTERVAL (isodow(make_date(Promo2SinceYear::INT, 1, 4)) - 1) DAY
         + INTERVAL ((Promo2SinceWeek::INT - 1) * 7) DAY END
                                            AS promo2_start_date,
    replace(coalesce(PromoInterval, ''), 'Sept', 'Sep') AS promo2_months
FROM bronze_stores;

CREATE OR REPLACE TABLE silver_daily AS
SELECT
    Store                         AS store_id,
    Date                          AS sales_date,
    Open = 1                      AS is_open,
    Sales                         AS sales,
    Customers                     AS customers,
    Promo = 1                     AS promo,
    CASE StateHoliday WHEN 'a' THEN 'public' WHEN 'b' THEN 'easter'
                      WHEN 'c' THEN 'christmas' ELSE 'none' END AS state_holiday,
    SchoolHoliday = '1'           AS school_holiday,
    -- Recording errors are kept but never trained on or scored: 54 days marked open with zero sales,
    -- and 14 days with sales under 10% of the store's median day (for example €46 at a €5,000 store)
    (Open = 1 AND Sales > 0 AND Sales >= 0.1 * store_median) AS is_valid_sale
FROM bronze_sales
JOIN (SELECT Store, median(Sales) AS store_median FROM bronze_sales WHERE Open = 1 AND Sales > 0 GROUP BY Store)
    USING (Store);
