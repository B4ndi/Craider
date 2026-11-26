import glob, sys
from sim import *
ALL = sorted({Path(f).name.split("-")[0] for f in glob.glob(str(DATA / "*-4h.feather"))})
data = load(ALL)
PER = {"20-23": ("2020-01-01", "2024-01-01"), "24+": ("2024-01-01", None), "full": ("2020-01-01", None)}
cache = {}
def evaluate(label, seeds=6, d=data, **kw):
    p0 = P(**kw)
    key = (p0.fast, p0.slow, p0.exit, id(d))
    if key not in cache: cache[key] = prepare(d, p0)
    row = {}
    for name, (s, e) in PER.items():
        ms = pd.DataFrame([metrics(run(d, P(seed=k, **kw), s, e, cache[key])[0]) for k in range(seeds)])
        row[name] = ms.median()
    f = lambda m: f"{m['cagr']*100:5.0f}%/yr dd{m['maxdd']*100:4.0f}%"
    print(f"{label:34}", " | ".join(f"{n} {f(m)}" for n, m in row.items()),
          f"| worstYr {row['full']['worst_year']*100:4.0f}% calmar {row['full']['calmar']:.2f}", flush=True)
    return row
