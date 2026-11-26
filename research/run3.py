from stress2 import *
B = dict(btc_filter=True, btc_exit=True)
for k in (5, 10, 15, 20):
    for sl in (5, 8, 10):
        evaluate(f"top{k} {sl} slots", topk=k, slots=sl, **B)
for tv in (0.5, 0.8):
    evaluate(f"top10 8 slots tvol{tv}", topk=10, slots=8, tvol=tv, **B)
    evaluate(f"top15 8 slots tvol{tv}", topk=15, slots=8, tvol=tv, **B)
