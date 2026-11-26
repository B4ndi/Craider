from sim import *
coins = "BTC ETH SOL BNB XRP ADA DOGE LINK AVAX LTC".split()
data = load(coins, source="freqtrade")
p = P()
prep = prepare(data, p)
for s, e in [("2020-01-01", "2024-01-01"), ("2024-01-01", None)]:
    curve, tr = run(data, p, s, e, prep)
    m = metrics(curve, tr)
    print(s, f"ret {m['ret']*100:.0f}%  trades {m['trades']}  mtmDD {m['maxdd']*100:.0f}%")
