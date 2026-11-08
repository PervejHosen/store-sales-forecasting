# Data

The project uses the **Rossmann Store Sales** dataset from Kaggle: daily sales for 1,115 Rossmann drugstores in Germany, 1 Jan 2013 to 31 Jul 2015.

The files are not included in this repository (the competition rules don't allow redistribution). To download them:

1. Sign in to Kaggle and accept the rules at https://www.kaggle.com/competitions/rossmann-store-sales
2. Download with the Kaggle CLI:
   ```bash
   kaggle competitions download -c rossmann-store-sales
   unzip rossmann-store-sales.zip train.csv store.csv -d data/raw
   ```
   or download `train.csv` and `store.csv` from the competition's Data tab and put them in `data/raw/`.

| File | Rows | What it holds |
|---|---|---|
| `train.csv` | 1,017,209 | One row per store and day: sales, customers, open flag, promotion, state and school holidays |
| `store.csv` | 1,115 | Store format, assortment, nearest competitor (distance, opening date) and the recurring Promo2 scheme |
