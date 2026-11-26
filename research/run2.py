from stress2 import *


evaluate("top10 by volume, 4 slots", topk=10)
evaluate("top10 by volume, 8 slots", topk=10, slots=8)
evaluate("btc filter", btc_filter=True)
evaluate("btc filter+exit", btc_filter=True, btc_exit=True)
evaluate("btc filter+exit, top10, 8 slots", btc_filter=True, btc_exit=True, topk=10, slots=8)
for sl in (0.08, 0.12): evaluate(f"sl {sl}", sl=sl)
for tr in (0.10, 0.20): evaluate(f"trail {tr}", trail=tr)
evaluate("kill switch 25%/30d", kill_dd=0.25)
