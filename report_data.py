"""Collect the gold tables and backtest results into report/data.js for the HTML report."""
import json, pathlib
import numpy as np, pandas as pd, duckdb

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "output"
MODELS = ["Seasonal naive", "Planner average", "ETS", "LightGBM"]
con = duckdb.connect(str(OUT / "forecast.duckdb"), read_only=True)
q = lambda s: con.sql(s).df()


def records(df):
    df = df.copy()
    for c in df.columns:
        if "datetime" in str(df[c].dtype) or "date" in str(df[c].dtype):
            df[c] = df[c].astype(str).str[:10]
    return json.loads(df.to_json(orient="records"))


def score(a, p):
    pe = (p - a) / a
    return dict(rmspe=float(np.sqrt(np.mean(pe ** 2))), wape=float(np.abs(p - a).sum() / a.sum()),
                bias=float(p.sum() / a.sum() - 1), off15=float(np.mean(np.abs(pe) > 0.15)))


pred = pd.read_parquet(OUT / "backtest_predictions.parquet")
feat = q("""SELECT store_id, sales_date, days_to_holiday, days_after_holiday, days_to_closure,
                   days_after_closure, state_holiday, school_holiday FROM gold_features WHERE is_valid_sale""")
feat["sales_date"] = pd.to_datetime(feat.sales_date)
pred = pred.merge(feat, on=["store_id", "sales_date"], how="left")
folds = list(dict.fromkeys(pred.fold))
D = {}

# ---- headline numbers
D["kpis"] = q("""SELECT (SELECT count(*) FROM bronze_sales) AS raw_rows,
                        (SELECT count(DISTINCT store_id) FROM silver_daily) AS stores,
                        (SELECT count(*) FROM silver_daily WHERE is_valid_sale) AS valid_days,
                        (SELECT count(*) FROM silver_daily WHERE is_open AND NOT is_valid_sale) AS zero_sale_days,
                        (SELECT min(sales_date)::VARCHAR FROM silver_daily) AS first_date,
                        (SELECT max(sales_date)::VARCHAR FROM silver_daily) AS last_date,
                        (SELECT round(sum(sales)) FROM silver_daily) AS total_sales""").iloc[0].to_dict()
D["kpis"] = {k: (v.item() if hasattr(v, "item") else v) for k, v in D["kpis"].items()}
D["kpis"]["scored_days"] = int(len(pred))

# ---- insight tables
for t in ["gold_weekday", "gold_promo_lift", "gold_school_holiday", "gold_weekly", "gold_competitor_event", "gold_store_types"]:
    D[t] = records(q(f"SELECT * FROM {t}"))

# ---- backtest scores
D["folds"] = [{"fold": f, "start": str(pred[pred.fold == f].sales_date.min().date()),
               "end": str(pred[pred.fold == f].sales_date.max().date()),
               "stores": int(pred[pred.fold == f].store_id.nunique()),
               "store_days": int((pred.fold == f).sum())} for f in folds]
D["by_fold"] = records(pd.read_csv(OUT / "backtest_metrics.csv"))
D["overall"] = [{"model": m, **score(pred.actual.to_numpy(), pred[m].to_numpy())} for m in MODELS]

# weekly totals per store (how rosters are planned)
wk = pred.assign(week=pred.sales_date.dt.to_period("W-SUN")).groupby(["fold", "store_id", "week"])[["actual", *MODELS]].sum()
D["weekly"] = [{"model": m, **score(wk.actual.to_numpy(), wk[m].to_numpy())} for m in MODELS]

# prediction interval coverage
inside = (pred.actual >= pred.p10) & (pred.actual <= pred.p90)
D["coverage"] = [{"fold": f, "coverage": float(inside[pred.fold == f].mean()),
                  "avg_width_pct": float(((pred.p90 - pred.p10) / pred.LightGBM)[pred.fold == f].mean())} for f in folds]
D["coverage_all"] = float(inside.mean())

# where the model struggles
def seg_scores(mask_name, mask):
    sub = pred[mask]
    return {"segment": mask_name, "store_days": int(len(sub)),
            **{m: score(sub.actual.to_numpy(), sub[m].to_numpy())["wape"] for m in ["Planner average", "LightGBM"]}}
D["segments"] = [
    seg_scores("All open days", pred.actual > 0),
    seg_scores("Promo days", pred.promo == 1),
    seg_scores("Non-promo days", pred.promo == 0),
    seg_scores("2 days before a public holiday", pred.days_to_holiday.between(1, 2)),
    seg_scores("First week after a refurbishment", pred.days_after_closure.between(1, 7) & (pred.days_after_holiday > 7)),
    seg_scores("Week before a refurbishment", pred.days_to_closure.between(1, 7) & (pred.days_to_holiday > 7)),
    seg_scores("School holidays", pred.school_holiday == 1),
]
D["by_store_type"] = [{"store_type": t, "stores": int(g.store_id.nunique()),
                       **{m: score(g.actual.to_numpy(), g[m].to_numpy())["wape"] for m in MODELS}}
                      for t, g in pred.groupby("store_type")]

# store-level accuracy in the latest window
last = pred[pred.fold == folds[-1]]
sw = last.groupby("store_id").apply(lambda g: pd.Series({
    "lgb": np.abs(g.LightGBM - g.actual).sum() / g.actual.sum(),
    "plan": np.abs(g["Planner average"] - g.actual).sum() / g.actual.sum()}), include_groups=False)
bins = [0, .04, .06, .08, .10, .12, .15, .20, 10]
labels = ["<4%", "4–6%", "6–8%", "8–10%", "10–12%", "12–15%", "15–20%", "20%+"]
D["store_hist"] = [{"bin": l, "LightGBM": int(a), "Planner average": int(b)} for l, a, b in zip(
    labels, pd.cut(sw.lgb, bins, labels=labels).value_counts().reindex(labels),
    pd.cut(sw.plan, bins, labels=labels).value_counts().reindex(labels))]
D["store_share_under10"] = {"LightGBM": float((sw.lgb < .10).mean()), "Planner average": float((sw.plan < .10).mean())}

# example stores for the explorer: a few typical ones of each format plus the hardest
sw = sw.join(last.groupby("store_id").store_type.first())
picks = []
for t in sorted(sw.store_type.unique()):
    s = sw[sw.store_type == t].sort_values("lgb")
    picks.append(int(s.index[len(s) // 2]))
picks.append(int(sw.lgb.idxmax()))
ex = []
for sid in picks:
    g = pred[pred.store_id == sid].sort_values("sales_date")
    ex.append({"store_id": sid, "store_type": g.store_type.iloc[0],
               "wape_last": float(sw.loc[sid, "lgb"]), "hardest": sid == picks[-1],
               "rows": records(g[["fold", "sales_date", "promo", "actual", "LightGBM", "p10", "p90", "Planner average"]].round(0))})
D["examples"] = ex

# what drives the forecast
imp = pd.read_csv(OUT / "feature_impact.csv", index_col=0).mean(axis=1)
groups = {"Store level and history": ["store_id", "lvl_90d_lag42", "dow_promo_90d_lag42", "ly_week_avg", "lag364"],
          "Promotions": ["promo", "promo2_running", "promo2_month"],
          "Weekday and season": ["dow", "day_of_month", "month", "week_of_year", "day_of_year"],
          "Holidays": ["state_holiday", "school_holiday", "days_to_holiday", "days_after_holiday"],
          "Refurbishment closures": ["days_to_closure", "days_after_closure"],
          "Competition": ["competition_distance_m", "competitor_open", "months_since_competitor"],
          "Store format": ["store_type", "assortment"]}
tot = imp.sum()
D["impact_groups"] = sorted([{"group": g, "share": float(imp[c].sum() / tot)} for g, c in groups.items()],
                            key=lambda r: -r["share"])
D["impact_top"] = [{"feature": f, "share": float(v / tot)} for f, v in imp.sort_values(ascending=False).head(12).items()]

(OUT / "report_data.json").write_text(json.dumps(D, default=str))
(ROOT / "report" / "data.js").write_text("const DATA = " + json.dumps(D, default=str, separators=(",", ":")) + ";\n")
print("wrote report/data.js")
