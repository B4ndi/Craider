from stress2 import *
C = dict(btc_filter=True, btc_exit=True, topk=10, slots=8, tvol=0.4)
p = P(**C); prep = prepare(data, p)
curves, trs = zip(*[run(data, P(seed=k, **C), "2020-01-01", None, prep) for k in range(10)])
yr = pd.DataFrame({k: c.resample("YE").last() for k, c in enumerate(curves)})
yr = pd.concat([pd.DataFrame({k: [1000.0] for k in yr}, index=[yr.index[0] - pd.offsets.YearEnd()]), yr])
btc = data["BTC"].close.loc["2020-01-01":].resample("YE").last()
btc = pd.concat([pd.Series([data["BTC"].close.loc["2020-01-01"].iloc[0]], index=[yr.index[0]]), btc])
out = pd.DataFrame({"bot median": yr.pct_change().median(axis=1), "bot worst seed": yr.pct_change().min(axis=1),
                    "BTC hold": btc.pct_change().values}, index=yr.index).iloc[1:]
out.index = out.index.year
print((out * 100).round(0).to_string())
m = pd.DataFrame([metrics(c) for c in curves])
print("\nfull period median:", f"{m.cagr.median()*100:.0f}%/yr, maxDD {m.maxdd.median()*100:.0f}% (worst seed {m.maxdd.min()*100:.0f}%)")
t = pd.concat(trs); print(f"trades/yr ~{len(t)/10/6.9:.0f}, win rate {(t.ret>0).mean()*100:.0f}%, avg win {t.ret[t.ret>0].mean()*100:.1f}%, avg loss {t.ret[t.ret<=0].mean()*100:.1f}%")
print("exposure (time with >=1 position):", f"{(pd.Series(curves[0]).diff()!=0).mean()*100:.0f}%")
b = data["BTC"].close.loc["2020-01-01":]; print("BTC hold maxDD", f"{(b/b.cummax()-1).min()*100:.0f}%")
