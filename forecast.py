"""Backtest four forecasting approaches on rolling 6-week windows.

Each fold trains only on data before the window starts and forecasts every open
store-day in the next 42 days. Scored on open days with recorded sales.
"""
import pathlib, json, time, warnings
import numpy as np, pandas as pd, duckdb, lightgbm as lgb

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "output"
H = 42  # forecast horizon in days

FOLDS = [  # (name, first forecast day)
    ("Christmas 2014", "2014-11-17"),
    ("Easter 2015", "2015-03-23"),
    ("May-Jun 2015", "2015-05-11"),
    ("Jun-Jul 2015", "2015-06-20"),
]

FEATURES = ["store_id", "store_type", "assortment", "dow", "day_of_month", "month", "week_of_year",
            "day_of_year", "promo", "state_holiday", "school_holiday", "days_to_holiday",
            "days_after_holiday", "days_to_closure", "days_after_closure", "competition_distance_m",
            "competitor_open", "months_since_competitor", "promo2_running", "promo2_month",
            "lvl_90d_lag42", "dow_promo_90d_lag42", "ly_week_avg", "lag364"]
CATS = ["store_id", "store_type", "assortment", "state_holiday"]
PARAMS = dict(learning_rate=0.05, num_leaves=63, min_data_in_leaf=50, feature_fraction=0.8,
              bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=7, num_threads=8)
ROUNDS = 800


def metrics(actual, pred):
    actual, pred = np.asarray(actual, float), np.asarray(pred, float)
    pe = (pred - actual) / actual
    return dict(rmspe=float(np.sqrt(np.mean(pe ** 2))),
                wape=float(np.abs(pred - actual).sum() / actual.sum()),
                bias=float(pred.sum() / actual.sum() - 1),
                off15=float(np.mean(np.abs(pe) > 0.15)))


def seasonal_naive(train, test):
    """Same weekday 52 weeks earlier; if the store was closed or has no data then, the last 8 weeks' weekday average."""
    hist = train.set_index(["store_id", "sales_date"])["sales"]
    key = pd.MultiIndex.from_arrays([test.store_id, test.sales_date - pd.Timedelta(days=364)])
    pred = hist.reindex(key).to_numpy()
    cutoff = test.sales_date.min()
    recent = train[train.sales_date >= cutoff - pd.Timedelta(days=56)]
    fb = recent.groupby(["store_id", "dow"]).sales.mean()
    fb = fb.reindex(pd.MultiIndex.from_arrays([test.store_id, test.dow])).to_numpy()
    return fill_gaps(np.where(np.isnan(pred), fb, pred), train, test)


def fill_gaps(pred, train, test):
    """Last resort for stores with no recent history (e.g. back from a long closure): all-history weekday average."""
    a = train.groupby(["store_id", "dow"]).sales.mean()
    a = a.reindex(pd.MultiIndex.from_arrays([test.store_id, test.dow])).to_numpy()
    b = test.store_id.map(train.groupby("store_id").sales.mean()).to_numpy()
    return np.where(np.isnan(pred), np.where(np.isnan(a), b, a), pred)


def planner_average(train, test):
    """What a planner would do by hand: the store's average for that weekday, split by promo week, over the last 12 weeks."""
    cutoff = test.sales_date.min()
    recent = train[train.sales_date >= cutoff - pd.Timedelta(days=84)]
    a = recent.groupby(["store_id", "dow", "promo"]).sales.mean()
    b = recent.groupby(["store_id", "dow"]).sales.mean()
    pa = a.reindex(pd.MultiIndex.from_arrays([test.store_id, test.dow, test.promo])).to_numpy()
    pb = b.reindex(pd.MultiIndex.from_arrays([test.store_id, test.dow])).to_numpy()
    return fill_gaps(np.where(np.isnan(pa), pb, pa), train, test)


def ets(train, test):
    """Per-store exponential smoothing (AutoETS, weekly season) on log sales of the last year.
    Closed days are filled with the store's weekday median so the weekly rhythm stays intact."""
    from statsforecast import StatsForecast
    from statsforecast.models import AutoETS
    cutoff = test.sales_date.min()
    start = cutoff - pd.Timedelta(days=364)
    stores = test.store_id.unique()
    tr = train[(train.sales_date >= start) & train.store_id.isin(stores)][["store_id", "sales_date", "log_sales", "dow"]]
    grid = pd.MultiIndex.from_product([stores, pd.date_range(start, cutoff - pd.Timedelta(days=1))],
                                      names=["store_id", "sales_date"]).to_frame(index=False)
    grid["dow"] = grid.sales_date.dt.isocalendar().day.astype(int)
    df = grid.merge(tr, on=["store_id", "sales_date", "dow"], how="left")
    med = df.groupby(["store_id", "dow"]).log_sales.transform("median")
    df["y"] = df.log_sales.fillna(med).fillna(df.groupby("store_id").log_sales.transform("median"))
    df = df.rename(columns={"store_id": "unique_id", "sales_date": "ds"})[["unique_id", "ds", "y"]]
    sf = StatsForecast(models=[AutoETS(season_length=7)], freq="D", n_jobs=-1)
    fc = sf.forecast(df=df, h=H)
    fc = fc.rename(columns={"unique_id": "store_id", "ds": "sales_date", "AutoETS": "p"})
    out = test[["store_id", "sales_date"]].merge(fc[["store_id", "sales_date", "p"]], how="left")
    return fill_gaps(np.exp(out.p.to_numpy()), train, test)


def to_lgb(df):
    X = df[FEATURES].copy()
    for c in CATS:
        X[c] = X[c].astype("category")
    return X


def lightgbm_models(train, test, cats_ref):
    Xtr, Xte = to_lgb(train), to_lgb(test)
    for c in CATS:  # identical category codes in train and test
        Xtr[c] = pd.Categorical(train[c], categories=cats_ref[c])
        Xte[c] = pd.Categorical(test[c], categories=cats_ref[c])
    y = train.log_sales.to_numpy()
    point = lgb.train({**PARAMS, "objective": "regression"}, lgb.Dataset(Xtr, y), ROUNDS)
    q = {}
    for a in (0.1, 0.9):
        m = lgb.train({**PARAMS, "objective": "quantile", "alpha": a, "learning_rate": 0.1}, lgb.Dataset(Xtr, y), 300)
        q[a] = np.exp(m.predict(Xte))
    contrib = point.predict(Xte.sample(20000, random_state=1), pred_contrib=True)
    shap = pd.Series(np.abs(contrib[:, :-1]).mean(0), index=FEATURES)
    return np.exp(point.predict(Xte)), q[0.1], q[0.9], shap


def main():
    con = duckdb.connect(str(OUT / "forecast.duckdb"), read_only=True)
    df = con.sql("SELECT * FROM gold_features WHERE is_valid_sale ORDER BY store_id, sales_date").df()
    df["sales_date"] = pd.to_datetime(df.sales_date)
    cats_ref = {c: sorted(df[c].unique()) for c in CATS}

    rows, preds, shaps = [], [], []
    for name, start in FOLDS:
        t0 = time.time()
        start = pd.Timestamp(start)
        end = start + pd.Timedelta(days=H - 1)
        train = df[df.sales_date < start]
        test = df[(df.sales_date >= start) & (df.sales_date <= end)].reset_index(drop=True)
        p = pd.DataFrame({"fold": name, "store_id": test.store_id, "sales_date": test.sales_date,
                          "store_type": test.store_type, "promo": test.promo, "actual": test.sales})
        log = lambda m: print(f"  {name}: {m} {time.time() - t0:.0f}s", flush=True)
        p["Seasonal naive"] = seasonal_naive(train, test)
        p["Planner average"] = planner_average(train, test)
        log("baselines")
        p["ETS"] = ets(train, test)
        log("ETS")
        p["LightGBM"], p["p10"], p["p90"], shap = lightgbm_models(train, test, cats_ref)
        shaps.append(shap.rename(name))
        for m in ["Seasonal naive", "Planner average", "ETS", "LightGBM"]:
            rows.append({"fold": name, "model": m, "store_days": len(p), "stores": p.store_id.nunique(),
                         **metrics(p.actual, p[m])})
        preds.append(p)
        print(f"{name}: {len(test):,} store-days, {time.time() - t0:.0f}s")

    res = pd.DataFrame(rows)
    pred = pd.concat(preds, ignore_index=True)
    res.to_csv(OUT / "backtest_metrics.csv", index=False)
    pred.to_parquet(OUT / "backtest_predictions.parquet", index=False)
    pd.concat(shaps, axis=1).to_csv(OUT / "feature_impact.csv")
    print(res.pivot(index="model", columns="fold", values="rmspe").round(3))


if __name__ == "__main__":
    main()
