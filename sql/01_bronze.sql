-- BRONZE: raw files loaded as published (Rossmann Store Sales, Kaggle)
CREATE OR REPLACE TABLE bronze_sales AS
SELECT * FROM read_csv('data/raw/train.csv', header = true,
    types = {'StateHoliday': 'VARCHAR', 'SchoolHoliday': 'VARCHAR'});

CREATE OR REPLACE TABLE bronze_stores AS
SELECT * FROM read_csv('data/raw/store.csv', header = true);
