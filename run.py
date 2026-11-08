"""Run the whole project: raw CSV -> bronze -> silver -> gold (SQL), backtests (Python), report data.
Usage:  pip install -r requirements.txt   then   python run.py
"""
import duckdb, os, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parent
os.chdir(ROOT)  # the SQL reads data/raw/... relative to the project folder
(ROOT / "output").mkdir(exist_ok=True)
for f in ["train.csv", "store.csv"]:
    if not (ROOT / "data" / "raw" / f).exists():
        sys.exit(f"Missing data/raw/{f}. See data/README.md for how to download it.")

con = duckdb.connect(str(ROOT / "output" / "forecast.duckdb"))
for sql in sorted((ROOT / "sql").glob("*.sql")):
    con.execute(sql.read_text())
    print("ran", sql.name)
con.close()

for step in ["forecast.py", "report_data.py"]:
    print("running", step)
    subprocess.run([sys.executable, str(ROOT / step)], check=True, cwd=ROOT)
