import time, glob
from sim import *
ALL = sorted({Path(f).name.split("-")[0] for f in glob.glob(str(DATA / "*-4h.feather"))})
data = load(ALL)
P1, P2, FULL = ("2020-01-01", "2024-01-01"), ("2024-01-01", None), ("2020-01-01", None)

def bench(s, e):
    cl = pd.DataFrame({c: d.close for c, d in data.items()})
    cl = cl.loc[s:e] if e else cl.loc[s:]
    live = cl.columns[cl.iloc[:6].notna().any()]  # coins tradable at the start
    rel = (cl[live].ffill() / cl[live].bfill().iloc[0]).mean(axis=1)
    return metrics(rel * 1000)

def fmt(m): return f"ret {m['ret']*100:7.0f}%  cagr {m['cagr']*100:5.0f}%  maxDD {m['maxdd']*100:4.0f}%  worstYr {m['worst_year']*100:4.0f}%"

print(len(ALL), "coins")
for name, (s, e) in [("2020-23", P1), ("2024+", P2), ("full", FULL)]:
    print(f"{name:8} hold-all   ", fmt(bench(s, e)))
t = time.time()
p = P(seed=0); prep = prepare(data, p)
for name, (s, e) in [("2020-23", P1), ("2024+", P2), ("full", FULL)]:
    ms = [metrics(run(data, P(seed=k), s, e, prep)[0]) for k in range(8)]
    df = pd.DataFrame(ms)
    print(f"{name:8} EmaTrend med", fmt(df.median()), f"| worst seed ret {df.ret.min()*100:.0f}% dd {df.maxdd.min()*100:.0f}%")
print(f"{time.time()-t:.0f}s")
