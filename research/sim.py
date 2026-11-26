"""Fast portfolio simulator for the EmaTrend family, mirroring Freqtrade's backtest rules:
signals on candle close, fills at next candle open, stoploss intra-candle (gap -> fill at open),
stake = free cash / free slots, fee per side, forced exit at a coin's last candle (delisting)."""
from dataclasses import dataclass
from pathlib import Path
import numpy as np, pandas as pd

DATA = Path(__file__).parent / "data"
FT_DATA = Path(__file__).parent.parent / "user_data/data/binance"


def ema(s, n):
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


@dataclass
class P:
    fast: int = 50
    slow: int = 200
    exit: int = 100
    sl: float = 0.20          # hard stoploss
    trail: float = 0.0        # trailing stop from peak (0 = off)
    btc_filter: bool = False  # only enter while BTC daily close > its 200-day SMA
    btc_exit: bool = False    # also close everything when the BTC filter turns off
    slots: int = 4
    fee: float = 0.001
    invest: float = 1.0       # fraction of equity the bot may use
    kill_dd: float = 0.0      # pause after this portfolio drawdown (0 = off)
    kill_days: int = 30
    seed: int | None = None   # None = fixed coin order, else random priority per candle
    tvol: float = 0.0         # volatility targeting: scale each stake by tvol / coin's annualized vol (0 = off)
    topk: int = 0             # only trade the top-k coins by 30-day dollar volume (0 = all)


def load(coins, tf="4h", source="research"):
    out = {}
    for c in coins:
        f = DATA / f"{c}-{tf}.feather" if source == "research" else FT_DATA / f"{c}_USDT-{tf}.feather"
        df = pd.read_feather(f)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        out[c] = df.set_index("date")[["open", "high", "low", "close", "volume"]]
    return out


def btc_regime(index):
    d = pd.read_feather(DATA / "BTC-1d.feather").set_index("date")["close"]
    bull = (d > d.rolling(200).mean()).shift(1)  # yesterday's completed daily candle: no look-ahead
    return bull.reindex(index, method="ffill").fillna(False).values


def prepare(data, p: P):
    idx = sorted(set().union(*[d.index for d in data.values()]))
    idx = pd.DatetimeIndex(idx)
    arr = {}
    for k in ("open", "high", "low", "close", "enter", "exit", "last", "dvol", "vol"):
        arr[k] = np.full((len(idx), len(data)), np.nan)
    for j, (c, d) in enumerate(data.items()):
        d = d.copy()
        ef, es, ex = ema(d.close, p.fast), ema(d.close, p.slow), ema(d.close, p.exit)
        d["enter"] = ((ef > es) & (d.close > ef) & ~(d.close < ex)).astype(float)
        d["exit"] = (d.close < ex).astype(float)
        d["dvol"] = (d.close * d.volume).rolling(180, min_periods=30).mean()
        d["vol"] = d.close.pct_change().rolling(180, min_periods=60).std() * np.sqrt(6 * 365)
        d["last"] = 0.0
        d.iloc[-1, d.columns.get_loc("last")] = 1.0
        d = d.reindex(idx)
        for k in arr: arr[k][:, j] = d[k].values
    dv = pd.DataFrame(arr["dvol"]).ffill(limit=6)
    dv[np.isnan(arr["close"])] = np.nan
    arr["vrank"] = dv.rank(axis=1, ascending=False).values
    return idx, arr


def run(data, p: P, start=None, end=None, prepared=None):
    idx, a = prepared or prepare(data, p)
    bull = btc_regime(idx) if (p.btc_filter or p.btc_exit) else np.ones(len(idx), bool)
    lo = idx.searchsorted(pd.Timestamp(start, tz="UTC")) if start else 0
    hi = idx.searchsorted(pd.Timestamp(end, tz="UTC")) if end else len(idx)
    n = a["close"].shape[1]
    rng = np.random.default_rng(p.seed) if p.seed is not None else None
    cash, eq0 = 1000.0, 1000.0
    pos = {}  # j -> dict(qty, entry, peak, stake)
    pend_in, pend_out = [], set()
    peak_eq, paused_until = eq0, -1
    curve, trades = np.empty(hi - lo), []
    reserve = eq0 * (1 - p.invest)

    def close_pos(j, price, t, why):
        nonlocal cash
        q = pos.pop(j)
        proceeds = q["qty"] * price * (1 - p.fee)
        cash += proceeds
        trades.append((idx[t], j, proceeds / q["stake"] - 1, why))

    for t in range(lo, hi):
        o, h, l, c = a["open"][t], a["high"][t], a["low"][t], a["close"][t]
        # 1) fills at this candle's open
        for j in list(pend_out):
            if j in pos and not np.isnan(o[j]): close_pos(j, o[j], t, "exit")
        pend_out.clear()
        for j in pend_in:
            if j in pos or len(pos) >= p.slots or np.isnan(o[j]): continue
            mtm = cash + sum(q["qty"] * a["close"][t - 1][k] for k, q in pos.items())
            usable = max(0.0, cash - reserve * mtm / eq0)  # keep the cash reserve aside
            stake = usable / (p.slots - len(pos))
            if p.tvol and not np.isnan(a["vol"][t - 1][j]):
                stake = min(stake, mtm / p.slots * p.tvol / a["vol"][t - 1][j])
            if stake < 10: continue
            cash -= stake
            pos[j] = dict(qty=stake * (1 - p.fee) / o[j], entry=o[j], peak=o[j], stake=stake)
        pend_in = []
        # 2) intra-candle stops
        for j in list(pos):
            if np.isnan(l[j]): continue
            q = pos[j]
            stop = q["entry"] * (1 - p.sl)
            if p.trail: stop = max(stop, q["peak"] * (1 - p.trail))
            if l[j] <= stop:
                close_pos(j, min(o[j], stop), t, "stop")
            else:
                q["peak"] = max(q["peak"], h[j])
        # 3) delisting / end of coin data
        for j in list(pos):
            if a["last"][t][j] == 1: close_pos(j, c[j], t, "delist")
        # 4) mark to market (missing candles valued at last known close)
        eq = cash
        for j, q in pos.items():
            px = c[j] if not np.isnan(c[j]) else q.get("lastpx", q["entry"])
            q["lastpx"] = px
            eq += q["qty"] * px
        curve[t - lo] = eq
        peak_eq = max(peak_eq, eq)
        # 5) kill switch
        if p.kill_dd and eq < peak_eq * (1 - p.kill_dd) and t > paused_until:
            pend_out |= set(pos)
            paused_until = t + p.kill_days * 6
            peak_eq = eq
        # 6) signals on this close -> act next open
        for j in pos:
            if a["exit"][t][j] == 1 or (p.btc_exit and not bull[t]): pend_out.add(j)
        if t >= paused_until and bull[t]:
            cand = [j for j in range(n) if a["enter"][t][j] == 1 and (not p.topk or a["vrank"][t][j] <= p.topk) and j not in pos and a["last"][t][j] != 1]
            if rng is not None: rng.shuffle(cand)
            pend_in = cand
    return pd.Series(curve, index=idx[lo:hi]), pd.DataFrame(trades, columns=["date", "coin", "ret", "why"])


def metrics(curve, trades=None):
    yrs = (curve.index[-1] - curve.index[0]).days / 365.25
    tot = curve.iloc[-1] / curve.iloc[0]
    dd = (curve / curve.cummax() - 1).min()
    yearly = curve.resample("YE").last().pct_change()
    yearly.iloc[0] = curve.resample("YE").last().iloc[0] / curve.iloc[0] - 1
    m = dict(ret=tot - 1, cagr=tot ** (1 / yrs) - 1, maxdd=dd, worst_year=yearly.min(),
             calmar=(tot ** (1 / yrs) - 1) / -dd if dd < 0 else np.inf)
    if trades is not None: m["trades"] = len(trades)
    return m
