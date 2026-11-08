"""Assemble the report page from its parts (dev helper, not needed to run the project)."""
import pathlib, sys
H = pathlib.Path(__file__).resolve().parent          # report/src
REPORT = H.parent
OUT = REPORT.parent / "output"
head = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Store Sales Forecasting · Pervej Hosen</title>
<meta name="description" content="Six-week daily sales forecasts for 1,115 drugstores: four methods backtested on rolling windows, LightGBM with prediction intervals, built with SQL and Python.">
<meta property="og:title" content="Store Sales Forecasting · Pervej Hosen">
<meta property="og:description" content="Six-week store sales forecasts, backtested honestly. SQL feature pipeline, LightGBM, prediction intervals.">
<link rel="icon" href="__FAVICON__" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
"""
css = (H / "_css.html").read_text().replace("</style>", (H / "_extra.css").read_text() + "</style>")
page = head + css + "\n</head>\n" + (H / "_body.html").read_text() + (H / "_script.html").read_text()
repo = "https://github.com/PervejHosen/store-sales-forecasting"
(REPORT / "index.html").write_text(page.replace("__REPO__", repo).replace("__HOME__", "https://pervejhosen.github.io/")
                              .replace("__FAVICON__", "https://pervejhosen.github.io/favicon.svg"))
OUT.mkdir(exist_ok=True)
(OUT / "site.html").write_text(page.replace("__REPO__", repo).replace("__HOME__", "../../").replace("__FAVICON__", "../../favicon.svg"))
print("built report/index.html (and output/site.html for the portfolio copy)")
