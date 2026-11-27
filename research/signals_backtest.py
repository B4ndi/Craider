"""Backtest two free data signals on top of the live Craider rules (see SIGNALS_BACKTEST.md):
1) altcoin-vs-BTC regime: only hold altcoins while an alt basket beats BTC, 2) BTC open-interest
(leverage) build-up. Live trading is unchanged; sim.run() only gained optional allow/scale hooks."""
import glob, sys, time
from sim import *

ALL = sorted({Path(f).name.split("-")[0] for f in glob.glob(str(DATA / "*-4h.feather"))})
data = load(ALL)
C = dict(btc_filter=True, btc_exit=True, topk=10, slots=8, tvol=0.4)
PER = {"20-23": ("2020-01-01", "2024-01-01"), "24+": ("2024-01-01", None), "full": ("2020-01-01", None)}
SEEDS = 10
PREP = prepare(data, P(**C))
IDX = PREP[0]
J = {c: j for j, c in enumerate(data)}

def daily(c):
    return pd.read_feather(DATA / f"{c}-1d.feather").set_index("date")

cl = pd.DataFrame({c: daily(c)["close"] for c in ALL})
dv = pd.DataFrame({c: (lambda d: d.close * d.volume)(daily(c)) for c in ALL}).rolling(30, min_periods=20).mean()

def to4h(s):
    """daily series (value known at end of that day) -> 4h candle index, usable from next day on."""
    s = s.copy(); s.index = s.index + pd.Timedelta(days=1)
    return s.reindex(IDX, method="ffill")

def evaluate(label, periods=PER, **kw):
    row = {}
    for name, (s, e) in periods.items():
        ms = pd.DataFrame([metrics(run(data, P(seed=k, **C), s, e, PREP, **kw)[0]) for k in range(SEEDS)])
        row[name] = ms.median()
    f = lambda m: f"{m['cagr']*100:5.1f}%/yr dd{m['maxdd']*100:4.0f}%"
    print(f"{label:44}", " | ".join(f"{n} {f(m)}" for n, m in row.items()),
          f"| worstYr {row['full']['worst_year']*100:4.0f}%", flush=True)
    return row

# ---------- 1) altcoin-vs-BTC regime ----------
def alt_index(majors=("BTC",), k=10):
    """equal-weight daily index of the top-k non-major coins by 30d dollar volume (ranks from yesterday)."""
    r = cl.pct_change(fill_method=None)
    alts = [c for c in ALL if c not in majors]
    rank = dv[alts].shift(1).rank(axis=1, ascending=False)
    w = (rank <= k).astype(float)
    ret = (r[alts].fillna(0) * w).sum(axis=1) / w.sum(axis=1).replace(0, np.nan)
    return (1 + ret.fillna(0)).cumprod()

def alt_regime(n, majors=("BTC",), raw=False):
    ratio = alt_index(majors) / cl["BTC"]
    on = ratio > ratio.rolling(n).mean()
    return on if raw else to4h(on).fillna(False).values

def mask(on, majors=("BTC",)):
    m = np.ones((len(IDX), len(data)), bool)
    for c, j in J.items():
        if c not in majors: m[:, j] = on
    return m

# ---------- 2) open-interest (leverage) build-up ----------
def oi_hot(L, q, coin="BTC", raw=False):
    """True while BTC open interest measured in BTC grew more over L days than its q-quantile of all
    earlier days (expanding window, first 180 days of OI data never fire)."""
    oi = pd.read_feather(DATA / f"{coin}-oi.feather").set_index("date")["oi"]
    chg = oi.pct_change(L)
    thr = chg.expanding(180).quantile(q).shift(1)
    hot = (chg > thr).reindex(cl.index).fillna(False)
    return hot if raw else to4h(hot).fillna(False).values.astype(bool)

if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "alt"  # alt | rot | oi | placebo | rotctl | size
    t0 = time.time()
    base = evaluate("Craider baseline")
    if what == "alt":
        print("--- alt regime: alts only while alt basket / BTC > its N-day average ---")
        for majors in (("BTC",), ("BTC", "ETH")):
            for n in (30, 60, 90, 120, 200):
                on = alt_regime(n, majors)
                tag = "+ETH" if "ETH" in majors else ""
                evaluate(f"N={n:3} majors=BTC{tag} block+exit (on {on.mean()*100:.0f}%)", allow=mask(on, majors))
                evaluate(f"N={n:3} majors=BTC{tag} block entries only", allow=mask(on, majors), allow_exit=False)
    if what == "rot":
        print("--- alt regime, rotate: when alts lag, block alts and let BTC (and ETH) take a k-times stake ---")
        for majors in (("BTC",), ("BTC", "ETH")):
            for n in (30, 60, 90):
                on = alt_regime(n, majors)
                for k in (2, 4):
                    sc = np.ones((len(IDX), len(data)))
                    for c in majors: sc[:, J[c]] = np.where(on, 1.0, k)
                    evaluate(f"N={n:3} majors={'+'.join(majors)} rotate x{k}", allow=mask(on, majors), scale=sc)
    if what == "oi":
        P2 = {"22-23": ("2022-01-01", "2024-01-01"), "24+": ("2024-01-01", None), "full": ("2022-01-01", None)}
        evaluate("Craider baseline (2022+)", P2)
        print("--- BTC open interest (in BTC) build-up over L days above its past q-quantile ---")
        for L in (7, 14, 30):
            for q in (0.8, 0.9):
                hot = oi_hot(L, q)
                every = np.ones((len(IDX), len(data)), bool)
                blk = mask(~hot, majors=())
                evaluate(f"L={L:2} q={q} block entries (hot {hot.mean()*100:.0f}%)", P2, allow=blk, allow_exit=False)
                evaluate(f"L={L:2} q={q} block + sell all", P2, allow=blk)
                evaluate(f"L={L:2} q={q} half-size entries", P2, scale=np.where(hot, 0.5, 1.0))
    print(f"{time.time()-t0:.0f}s")

def placebo(hot, n=40, seed=0, periods=None, **kw):
    """Same mask, circularly shifted by a random offset within the OI era: keeps how often and how long
    it fires, breaks the link to real leverage. Returns full-period CAGRs."""
    rng = np.random.default_rng(seed)
    s, e = periods["full"]
    lo = IDX.searchsorted(pd.Timestamp(s, tz="UTC"))
    out = []
    for _ in range(n):
        h = hot.copy(); k = rng.integers(180 * 6, (len(IDX) - lo) - 180 * 6)
        h[lo:] = np.roll(hot[lo:], k)
        r = evaluate("  placebo", {"full": (s, e)}, allow=mask(~h, majors=()), **kw)
        out.append(r["full"]["cagr"])
    return np.array(out)

if __name__ == "__main__" and what == "placebo":
    P2 = {"full": ("2022-01-01", None)}
    for L in (7, 14):
        hot = oi_hot(L, 0.9)
        real = evaluate(f"REAL L={L} q=0.9 block entries", P2, allow=mask(~hot, majors=()), allow_exit=False)["full"]["cagr"]
        pl = placebo(hot, periods=P2, allow_exit=False, seed=L)
        print(f"L={L}: real {real*100:.1f}%/yr, placebo median {np.median(pl)*100:.1f}%, "
              f"{(pl >= real).mean()*100:.0f}% of placebos >= real, range {pl.min()*100:.1f}..{pl.max()*100:.1f}", flush=True)

if __name__ == "__main__" and what == "rotctl":
    M = ("BTC", "ETH")
    def rot(on, k=4):
        sc = np.ones((len(IDX), len(data)))
        for c in M: sc[:, J[c]] = np.where(on, 1.0, k)
        return dict(allow=mask(on, M), scale=sc)
    T = np.ones(len(IDX), bool)
    sc = np.ones((len(IDX), len(data))); sc[:, J["BTC"]] = sc[:, J["ETH"]] = 4
    evaluate("control: BTC/ETH always x4, alts allowed", scale=sc)
    evaluate("control: BTC/ETH only x4 (alts never)", **rot(~T))
    for n in (30, 60):
        on = alt_regime(n, M)
        real = evaluate(f"REAL N={n} rotate x4", **rot(on))
        rng = np.random.default_rng(n); pl = []
        for _ in range(30):
            k = rng.integers(365 * 6, len(IDX) - 365 * 6)
            pl.append(evaluate("  placebo", {"full": PER["full"], "24+": PER["24+"]}, **rot(np.roll(on, k))))
        f = np.array([p["full"]["cagr"] for p in pl]); g = np.array([p["24+"]["cagr"] for p in pl])
        print(f"N={n}: full real {real['full']['cagr']*100:.1f} vs placebo median {np.median(f)*100:.1f} "
              f"({(f >= real['full']['cagr']).mean()*100:.0f}% >= real); 24+ real {real['24+']['cagr']*100:.1f} "
              f"vs {np.median(g)*100:.1f} ({(g >= real['24+']['cagr']).mean()*100:.0f}% >= real)", flush=True)

if __name__ == "__main__" and what == "size":
    print("--- sizing controls (not a data signal): bigger stakes for BTC/ETH vs bigger stakes for all ---")
    for k in (1.5, 2, 3, 4):
        sc = np.ones((len(IDX), len(data))); sc[:, J["BTC"]] = sc[:, J["ETH"]] = k
        evaluate(f"BTC/ETH stakes x{k}", scale=sc)
    for k in (1.5, 2, 4):
        evaluate(f"all coins stakes x{k}", scale=np.full(len(IDX), float(k)))
    sc = np.ones((len(IDX), len(data))); sc[:, J["BTC"]] = sc[:, J["ETH"]] = 4
    for k in range(SEEDS):
        cur, tr = run(data, P(seed=k, **C), "2020-01-01", None, PREP, scale=sc)
        b, _ = run(data, P(seed=k, **C), "2020-01-01", None, PREP)
        if k == 0:
            yr = lambda x: (x.resample("YE").last() / x.resample("YE").last().shift(1).fillna(1000) - 1) * 100
            print("years base :", yr(b).round(0).tolist()); print("years x4  :", yr(cur).round(0).tolist())
