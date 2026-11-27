"""Does a cybersecurity-news alarm (exchange hacks, withdrawal halts, stablecoin depegs) improve Craider?

Compares the live Craider rules with and without a "news exit": when an incident from incidents.csv
becomes public (+ an extra delay for how late our news feed is), sell everything at the next 4h open
and take no new entries for `pause` days. After the pause the normal Craider rules re-enter.

Also runs:
  * a placebo test: the same number of alarms at random times, to see whether the real alarms beat luck;
  * an event study: what BTC did in the hours/days after each alarm, vs. any random moment.

Run from research/ after fetch.py, fetch2.py and the fng download (see README):
    python news_backtest.py            # writes results to stdout and data/news_backtest.json
"""
import json, sys
import numpy as np, pandas as pd
from sim import P, DATA, load, prepare, run, metrics, btc_regime
from pathlib import Path

HERE = Path(__file__).parent
CRAIDER = dict(btc_filter=True, btc_exit=True, topk=10, slots=8, tvol=0.4)   # == live strategy
START = "2020-01-01"
SEEDS = 10
CANDLE = pd.Timedelta("4h")


def incidents(tiers="AB"):
    df = pd.read_csv(HERE / "incidents.csv", comment="#")
    df["time"] = pd.to_datetime(df["time_utc"], utc=True)
    return df[df.tier.isin(list(tiers))].reset_index(drop=True)


def halt_mask(idx, times, lag_h, pause_d):
    """True on every candle whose close falls in [alert, alert + pause): the exit then fills at the
    first 4h open at/after alert = news time + lag, and entries stay blocked until the pause ends."""
    m = np.zeros(len(idx), bool)
    close = idx + CANDLE
    for t in times:
        a = t + pd.Timedelta(hours=lag_h)
        m |= (close >= a) & (close < a + pd.Timedelta(days=pause_d) + CANDLE)
    return m


def evaluate(data, prep, halt=None, seeds=SEEDS):
    curves = [run(data, P(seed=k, **CRAIDER), START, None, prep, halt)[0] for k in range(seeds)]
    m = pd.DataFrame([metrics(c) for c in curves])
    return dict(cagr=m.cagr.median(), maxdd=m.maxdd.median(), worst_year=m.worst_year.median(),
                calmar=m.calmar.median()), curves


def fmt(r):
    return f"CAGR {r['cagr']*100:5.1f}%  maxDD {r['maxdd']*100:5.1f}%  worst yr {r['worst_year']*100:5.1f}%  calmar {r['calmar']:.2f}"


def main():
    coins = sorted({p.name.split("-")[0] for p in DATA.glob("*-4h.feather")})
    data = load(coins)
    prep = prepare(data, P(**CRAIDER))
    idx = prep[0]
    lo = idx.searchsorted(pd.Timestamp(START, tz="UTC"))
    bull = btc_regime(idx).astype(bool)
    out = {}

    base, base_curves = evaluate(data, prep)
    out["baseline"] = base
    print("Baseline Craider (no news exits):".ljust(46), fmt(base), flush=True)

    # --- 1) Exposure: was the bot even invested when each incident hit? ---
    inc = incidents()
    eq0 = base_curves[0]
    pos_idx = np.clip(idx.searchsorted(inc.time) - 1, 0, len(idx) - 1)
    inc["btc_bull"] = bull[pos_idx]
    # invested = equity moved over the 4h candle at the incident (fixed-order seed 0 curve)
    ch = eq0.pct_change().abs()
    inc["invested"] = [bool(ch.reindex([idx[i], idx[min(i + 1, len(idx) - 1)]]).fillna(0).gt(0).any()) for i in pos_idx]
    print(f"\n{len(inc)} incidents; bot invested at {inc.invested.sum()} of them "
          f"(BTC above 200d SMA at {inc.btc_bull.sum()})", flush=True)

    # --- 2) Event study: BTC return after each alert vs. unconditional ---
    btc = data["BTC"].close.reindex(idx).ffill()
    hz = {"4h": 1, "1d": 6, "3d": 18, "7d": 42}
    rows = []
    for _, r in inc.iterrows():
        i = idx.searchsorted(r.time)  # first open at/after the news
        row = dict(time=str(r.time)[:16], tier=r.tier, event=r.event, invested=r.invested)
        for name, k in hz.items():
            if i + k < len(idx): row[name] = btc.iloc[min(i + k, len(btc) - 1)] / btc.iloc[i] - 1 if i < len(btc) else np.nan
        rows.append(row)
    ev = pd.DataFrame(rows)
    b = btc.loc[START:]
    uncond = {n: (b.shift(-k) / b - 1).dropna() for n, k in hz.items()}
    print("\nBTC return after alert (median / mean / share negative) vs any moment:")
    es = {}
    for n in hz:
        for tier in ("A", "B", "AB"):
            x = ev[ev.tier.isin(list(tier))][n].dropna()
            es[f"{tier}_{n}"] = dict(n=len(x), median=x.median(), mean=x.mean(), neg=(x < 0).mean())
        u = uncond[n]
        es[f"all_{n}"] = dict(median=u.median(), mean=u.mean(), neg=(u < 0).mean())
        print(f"  {n:>3}: tier A {es[f'A_{n}']['median']*100:+5.1f}% / {es[f'A_{n}']['mean']*100:+5.1f}% / {es[f'A_{n}']['neg']*100:3.0f}%   "
              f"all incidents {es[f'AB_{n}']['median']*100:+5.1f}% / {es[f'AB_{n}']['mean']*100:+5.1f}% / {es[f'AB_{n}']['neg']*100:3.0f}%   "
              f"random moment {u.median()*100:+5.1f}% / {u.mean()*100:+5.1f}% / {(u<0).mean()*100:3.0f}%")

    # 2b) Same for what Craider actually holds: the top-10 coins by volume (equal weight), and only for
    # alarms that hit in a bull market (in a bear market the bot is in cash). Compared with the mean of
    # equally many random bull-market moments (2000 draws).
    _, a = prep
    cl, vr = pd.DataFrame(a["close"], index=idx), pd.DataFrame(a["vrank"], index=idx)
    at = np.clip(idx.searchsorted(inc.time), 0, len(idx) - 1)
    in_bull = bull[np.clip(at - 1, 0, None)]
    pool = np.where(bull & (np.arange(len(idx)) >= lo))[0]
    rng = np.random.default_rng(1)
    print(f"\nTop-10 coin basket after the {in_bull.sum()} alarms that hit in a bull market (mean, vs random bull moments):")
    for name, k in (("1d", 6), ("3d", 18), ("7d", 42), ("14d", 84)):
        fwd = (cl.shift(-k) / cl - 1).where(vr <= 10).mean(axis=1).values
        x = np.nanmean(fwd[at[in_bull]])
        pp = pool[~np.isnan(fwd[pool])]
        null = np.array([fwd[rng.choice(pp, in_bull.sum())].mean() for _ in range(2000)])
        lower = (null < x).mean()
        es[f"basket_{name}"] = dict(alarms_mean=float(x), random_mean=float(null.mean()), share_random_below=float(lower))
        print(f"  {name:>3}: after alarms {x*100:+5.1f}%   random {null.mean()*100:+5.1f}%   "
              f"({lower*100:.0f}% of random draws were lower)")
    out["event_study"] = es
    out["events"] = ev.assign(**{k: ev[k].round(4) for k in hz}).to_dict("records")

    # --- 3) Strategy with news exits: sweep tiers x delay x pause ---
    print("\nWith news exits (median of 10 seeds):")
    grid = []
    for tiers in ("A", "AB"):
        times = incidents(tiers).time
        for lag in (0, 4, 12, 24):
            for pause in (1, 3, 7, 14):
                r, _ = evaluate(data, prep, halt_mask(idx, times, lag, pause))
                r.update(tiers=tiers, lag_h=lag, pause_d=pause, d_cagr=r["cagr"] - base["cagr"], d_maxdd=r["maxdd"] - base["maxdd"])
                grid.append(r)
                print(f"  tiers {tiers:2} delay {lag:2}h pause {pause:2}d".ljust(46), fmt(r),
                      f"  dCAGR {r['d_cagr']*100:+5.2f}pp  dMaxDD {r['d_maxdd']*100:+5.2f}pp", flush=True)
    out["grid"] = grid
    print("\nSub-periods (median of 10 seeds):")
    sub = []
    for tiers, lag, pause in (("A", 4, 3), ("AB", 4, 3), ("AB", 24, 14)):
        for s0, e0 in (("2020-01-01", "2024-01-01"), ("2024-01-01", None)):
            h = halt_mask(idx, incidents(tiers).time, lag, pause)
            b0 = np.median([metrics(run(data, P(seed=k, **CRAIDER), s0, e0, prep)[0])["cagr"] for k in range(SEEDS)])
            n0 = np.median([metrics(run(data, P(seed=k, **CRAIDER), s0, e0, prep, h)[0])["cagr"] for k in range(SEEDS)])
            sub.append(dict(tiers=tiers, lag_h=lag, pause_d=pause, start=s0, end=e0, base=b0, news=n0))
            print(f"  tiers {tiers:2} delay {lag:2}h pause {pause:2}d  {s0[:4]}-{(e0 or 'now')[:4]}: "
                  f"without {b0*100:5.1f}%/yr  with {n0*100:5.1f}%/yr", flush=True)
    out["subperiods"] = sub

    # --- 4) Per-incident P&L: what did each alarm alone save or cost? (seed 0 = fixed order) ---
    print("\nPer-incident effect (tier A+B, 4h delay, 3d pause, fixed coin order):")
    base0 = run(data, P(**CRAIDER), START, None, prep)[0]
    per = []
    for _, r in inc.iterrows():
        c = run(data, P(**CRAIDER), START, None, prep, halt_mask(idx, [r.time], 4, 3))[0]
        d = c.iloc[-1] / base0.iloc[-1] - 1
        if abs(d) > 1e-9:
            per.append(dict(time=str(r.time)[:16], tier=r.tier, event=r.event, final_equity_change=round(d, 4)))
            print(f"  {str(r.time)[:10]} {r.tier} {r.event[:48]:48} {d*100:+6.2f}% final equity")
    out["per_incident"] = per
    print(f"  ({len(inc) - len(per)} incidents had no effect: bot was in cash)")

    # --- 5) Placebo: same number of alarms at random moments ---
    # Checked for the default setting (4h delay, 3d pause) and for the best-looking cell of the grid,
    # since picking the best of 32 settings flatters it.
    print("\nPlacebo (random alarm times inside bull markets, fixed coin order, 200 draws):")
    # Fair placebo: hacks cluster in bear markets, when Craider is in cash anyway, so random alarms
    # spread over all time would hit invested periods more often than the real ones. Draw random
    # alarms only from bull-regime candles, as many as real alarms that fell in the bull regime.
    rng = np.random.default_rng(7)
    ok = bull.copy(); ok[:lo] = False; ok[-60:] = False
    span = idx[ok]
    best = max(grid, key=lambda r: r["cagr"])
    pl = {}
    for tiers, lag, pause in (("AB", 4, 3), ("A", 4, 3), (best["tiers"], best["lag_h"], best["pause_d"])):
        times = incidents(tiers).time
        n_bull = int(bull[np.clip(idx.searchsorted(times) - 1, 0, len(idx) - 1)].sum())
        rc = metrics(run(data, P(**CRAIDER), START, None, prep, halt_mask(idx, times, lag, pause))[0])["cagr"]
        draws = np.array([metrics(run(data, P(**CRAIDER), START, None, prep, halt_mask(
            idx, pd.DatetimeIndex(rng.choice(span, n_bull, replace=False)), lag, pause))[0])["cagr"] for _ in range(200)])
        pct = (draws < rc).mean()
        key = f"{tiers}_{lag}h_{pause}d"
        pl[key] = dict(real_cagr=rc, placebo_median=float(np.median(draws)), placebo_p05=float(np.quantile(draws, .05)),
                       placebo_p95=float(np.quantile(draws, .95)), real_percentile=float(pct))
        pl[key]["n_random_alarms"] = n_bull
        print(f"  tiers {tiers:2} delay {lag:2}h pause {pause:2}d ({n_bull} in bull market): real alarms CAGR {rc*100:.1f}% vs random alarms median "
              f"{np.median(draws)*100:.1f}% (5-95%: {np.quantile(draws,.05)*100:.1f}-{np.quantile(draws,.95)*100:.1f}%)"
              f" -> real beats {pct*100:.0f}% of random", flush=True)
    out["placebo"] = pl
    out["baseline_fixed_order_cagr"] = metrics(base0)["cagr"]

    json.dump(out, open(DATA / "news_backtest.json", "w"), indent=1, default=float)
    print(f"\nwrote {DATA / 'news_backtest.json'}")


if __name__ == "__main__":
    main()
