"""Download 4h + 1d Binance spot klines for a broad universe, including delisted coins."""
import io, zipfile, sys, concurrent.futures as cf
from pathlib import Path
import pandas as pd, requests

OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)
START = pd.Timestamp("2020-01-01", tz="UTC")
LISTED = ("BTC ETH XRP BCH LTC BNB XTZ XLM ADA TRX LINK ETC NEO DASH ATOM IOTA ZEC DOT UNI THETA "
          "VET FIL LUNA SOL AVAX DOGE NEAR ALGO FTT ICP AXS SAND MANA EGLD CHZ AAVE HBAR").split()
DELISTED = "EOS XMR MATIC FTM".split()
COLS = ["date", "open", "high", "low", "close", "volume"]
S = requests.Session()


def api(sym, tf):
    rows, t = [], int(START.timestamp() * 1000)
    while True:
        r = S.get("https://data-api.binance.vision/api/v3/klines",
                  params=dict(symbol=sym, interval=tf, startTime=t, limit=1000), timeout=30).json()
        if not r: break
        rows += r
        t = r[-1][0] + 1
        if len(r) < 1000: break
    return rows


def zips(sym, tf):
    rows = []
    for m in pd.period_range("2020-01", "2026-10", freq="M"):
        u = f"https://data.binance.vision/data/spot/monthly/klines/{sym}/{tf}/{sym}-{tf}-{m}.zip"
        r = S.get(u, timeout=30)
        if r.status_code != 200: continue
        z = zipfile.ZipFile(io.BytesIO(r.content))
        rows += pd.read_csv(z.open(z.namelist()[0]), header=None).values.tolist()
    return rows


def get(coin, tf):
    sym = coin + "USDT"
    rows = zips(sym, tf) if coin in DELISTED else api(sym, tf)
    df = pd.DataFrame([r[:6] for r in rows], columns=COLS)
    ts = df["date"].astype("int64")
    ts = ts.where(ts < 1e14, ts // 1000)  # 2025+ archive files use microseconds
    df["date"] = pd.to_datetime(ts, unit="ms", utc=True)
    df = df.astype({c: float for c in COLS[1:]}).drop_duplicates("date").sort_values("date")
    if coin == "LUNA":  # old LUNA collapsed and was delisted; LUNA 2.0 is a different coin
        df = df[df["date"] < "2022-05-14"]
    df.to_feather(OUT / f"{coin}-{tf}.feather")
    return coin, tf, len(df), df["date"].iloc[0].date(), df["date"].iloc[-1].date()


if __name__ == "__main__":
    jobs = [(c, tf) for c in LISTED + DELISTED for tf in ("4h", "1d")]
    with cf.ThreadPoolExecutor(4) as ex:
        for res in ex.map(lambda j: get(*j), jobs):
            if res[1] == "1d": print(*res, flush=True)
