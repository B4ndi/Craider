import glob, json
from sim import *
ALL = sorted({Path(f).name.split("-")[0] for f in glob.glob(str(DATA / "*-1d.feather"))})
cl = pd.DataFrame({c: pd.read_feather(DATA / f"{c}-1d.feather").set_index("date")["close"] for c in ALL})
vol = pd.DataFrame({c: (lambda d: d.close * d.volume)(pd.read_feather(DATA / f"{c}-1d.feather").set_index("date")) for c in ALL})
ret = cl.pct_change(fill_method=None).fillna(0)
alive = cl.notna()
dvol30 = vol.rolling(30, min_periods=20).mean().where(alive)
btc = cl["BTC"]; bull = (btc > btc.rolling(200).mean()).shift(1).fillna(False)
PER = {"20-23": ("2020-01-01", "2023-12-31"), "24+": ("2024-01-01", None), "full": ("2020-01-01", None)}

def report(name, daily):
    row = []
    for n, (s, e) in PER.items():
        r = daily.loc[s:e] if e else daily.loc[s:]
        m = metrics((1 + r).cumprod() * 1000)
        row.append(f"{n} {m['cagr']*100:5.0f}%/yr dd{m['maxdd']*100:4.0f}%")
    m = metrics((1 + daily.loc["2020-01-01":]).cumprod() * 1000)
    print(f"{name:40}", " | ".join(row), f"| worstYr {m['worst_year']*100:4.0f}%")

def xsmom(look=28, k=3, filt=True, topk=10, fee=0.001, volw=True):
    w = pd.DataFrame(0.0, index=cl.index, columns=ALL)
    mom = cl.pct_change(look, fill_method=None)
    rv = ret.rolling(60).std() * np.sqrt(365)
    for d in cl.index[cl.index.day_of_week == 0]:
        i = cl.index.get_loc(d)
        if i < 220 or (filt and not bull.iloc[i]): continue
        univ = dvol30.iloc[i - 1].nlargest(topk).index
        m = mom.iloc[i - 1][univ].dropna()
        m = m[m > 0].nlargest(k)
        if len(m) == 0: continue
        if volw:
            iv = (0.4 / rv.iloc[i - 1][m.index]).clip(upper=1.0) / k
            w.loc[d, m.index] = iv.values
        else:
            w.loc[d, m.index] = 1 / k
    w = w[w.index.day_of_week == 0].reindex(w.index).ffill().fillna(0)
    # if a weekly rebalance day was skipped due to filter, it's flat (all zeros) - correct
    if filt:  # exit immediately (daily) when BTC regime turns off
        w[~bull.values] = 0
    w = w.where(alive, 0)
    turnover = w.diff().abs().sum(axis=1)
    return (w.shift(1) * ret).sum(axis=1) - turnover.shift(1).fillna(0) * fee

for look in (14, 28, 56):
    for k in (3, 5):
        report(f"xs-momentum look{look}d top{k}", xsmom(look, k))
report("xs-momentum look28 top3 no BTC filter", xsmom(28, 3, filt=False))

# Fear & Greed contrarian on BTC
fng = json.load(open(DATA / "fng.json"))["data"]
f = pd.Series({pd.Timestamp(int(x["timestamp"]), unit="s", tz="UTC"): int(x["value"]) for x in fng}).sort_index()
f = f.reindex(cl.index).ffill().shift(1)
for buy, sell in [(20, 60), (25, 75), (15, 50)]:
    pos = pd.Series(np.nan, index=cl.index); pos[f < buy] = 1; pos[f > sell] = 0; pos = pos.ffill().fillna(0)
    report(f"BTC: buy F&G<{buy}, sell F&G>{sell}", pos.shift(1) * ret["BTC"] - pos.diff().abs().shift(1).fillna(0) * 0.001)
report("BTC buy & hold", ret["BTC"])
report("BTC only while > 200d SMA", bull.astype(float).shift(1).fillna(0) * ret["BTC"] - bull.astype(float).diff().abs().fillna(0) * 0.001)
