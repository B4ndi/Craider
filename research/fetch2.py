"""Funding-rate history (Binance USDT-M perps) for sentiment/carry research."""
import io, zipfile, concurrent.futures as cf
from pathlib import Path
import pandas as pd, requests
OUT = Path(__file__).parent / "data"; S = requests.Session()
COINS = "BTC ETH XRP BCH LTC BNB XLM ADA TRX LINK ETC DOT UNI SOL AVAX DOGE NEAR ATOM FIL AAVE".split()

def get(u):
    import time
    for i in range(5):
        try: return S.get(u, timeout=30)
        except requests.RequestException: time.sleep(2 * (i + 1))
    raise RuntimeError(u)

def funding(coin):
    if (OUT / f"{coin}-funding.feather").exists():
        df = pd.read_feather(OUT / f"{coin}-funding.feather"); return coin, len(df), df.date.iloc[0].date(), df.rate.mean() * 3 * 365
    sym, rows = coin + "USDT", []
    for m in pd.period_range("2020-01", "2026-10", freq="M"):
        r = get(f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{sym}/{sym}-fundingRate-{m}.zip")
        if r.status_code != 200: continue
        z = zipfile.ZipFile(io.BytesIO(r.content))
        df = pd.read_csv(z.open(z.namelist()[0]))
        if not str(df.columns[0]).startswith("calc"): df = pd.read_csv(z.open(z.namelist()[0]), header=None, names=["calc_time","funding_interval_hours","last_funding_rate"])
        rows.append(df)
    df = pd.concat(rows)
    df["date"] = pd.to_datetime(df.iloc[:, 0].astype("int64"), unit="ms", utc=True)
    df = df[["date", "last_funding_rate"]].rename(columns={"last_funding_rate": "rate"}).sort_values("date")
    df.to_feather(OUT / f"{coin}-funding.feather")
    return coin, len(df), df.date.iloc[0].date(), df.rate.mean() * 3 * 365

with cf.ThreadPoolExecutor(4) as ex:
    for r in ex.map(funding, COINS): print(*r)
