"""Open-interest history (Binance USDT-M perps, 5-min 'metrics' files, from Dec 2021) for BTC and ETH.
Saved as daily last values: open interest in coins and in USD."""
import io, zipfile, concurrent.futures as cf, time
from pathlib import Path
import pandas as pd, requests
OUT = Path(__file__).parent / "data"; S = requests.Session()

def day(sym, d):
    u = f"https://data.binance.vision/data/futures/um/daily/metrics/{sym}/{sym}-metrics-{d:%Y-%m-%d}.zip"
    for i in range(5):
        try:
            r = S.get(u, timeout=30)
            if r.status_code != 200: return None
            z = zipfile.ZipFile(io.BytesIO(r.content))
            return pd.read_csv(z.open(z.namelist()[0]))
        except Exception: time.sleep(2 * (i + 1))
    return None

def coin(c):
    sym = c + "USDT"
    days = pd.date_range("2021-12-01", "2026-11-25", freq="D")
    with cf.ThreadPoolExecutor(16) as ex: dfs = [d for d in ex.map(lambda d: day(sym, d), days) if d is not None]
    df = pd.concat(dfs)
    df["date"] = pd.to_datetime(df.create_time, utc=True)
    df = df.sort_values("date").set_index("date")[["sum_open_interest", "sum_open_interest_value"]].astype(float)
    df = df.resample("1D").last().dropna().rename(columns={"sum_open_interest": "oi", "sum_open_interest_value": "oi_usd"})
    df.reset_index().to_feather(OUT / f"{c}-oi.feather")
    print(c, len(df), df.index[0].date(), df.index[-1].date(), flush=True)

if __name__ == "__main__":
    for c in ("BTC", "ETH"): coin(c)
