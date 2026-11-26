from stress2 import *
C = dict(btc_filter=True, btc_exit=True, topk=10, slots=8, tvol=0.5)
print("--- EMA settings (fast/slow/exit) ---")
for f, s, x in [(50,200,100),(30,150,60),(40,200,80),(60,200,120),(50,150,100),(50,250,100),(80,300,150),(20,100,50),(50,200,50),(50,200,150)]:
    evaluate(f"ema {f}/{s}/{x}", fast=f, slow=s, exit=x, **C)
print("--- fees (incl. slippage) ---")
for fee in (0.002, 0.003): evaluate(f"fee {fee*100:.1f}% per side", fee=fee, **C)
print("--- ablation ---")
evaluate("no btc filter", **{**C, "btc_filter": False, "btc_exit": False})
evaluate("btc filter, no btc exit", **{**C, "btc_exit": False})
for tv in (0.3, 0.4): evaluate(f"tvol {tv}", **{**C, "tvol": tv})
for sl in (0.12, 0.30): evaluate(f"stoploss {sl}", sl=sl, **C)
