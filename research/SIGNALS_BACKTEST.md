# Do free market-data signals improve Craider?

**Conclusion: no. Neither signal is worth adding to the live bot.**

* **Altcoins vs BTC.** This rule only holds altcoins while a basket of altcoins is beating BTC. It
  makes Craider clearly worse: **7–19%/yr instead of 29%/yr**, in both 2020–23 and 2024+. A
  "rotate into BTC/ETH" version looks good from 2024 on (+12 pp/yr), but over the full period it
  doesn't beat a placebo. Most of its gain comes from simply giving BTC and ETH bigger stakes.
* **Open interest (leverage build-up).** This rule skips new entries while borrowed bets on BTC are
  piling up unusually fast. It is roughly neutral: **+0.3 to +1.0 pp/yr** over 2022–2026, using
  the 2 best of 18 settings. Those 2 settings beat 92–95% of placebos. That is too small, and too
  much the result of picking the best settings, to trust.
* **Side finding (not a data signal):** giving BTC and ETH larger stakes than altcoins raises
  returns, at the cost of somewhat deeper drops. It's a risk choice, so it's noted here and not
  adopted.

Live trading is unchanged. `sim.py` only gains optional `allow` / `scale` arguments, which are
off by default. The baseline still reproduces 29.3%/yr with a −23.2% worst drop.

## Method

* **Strategy:** the live Craider rules (EMA trend on 4h, BTC > 200-day SMA filter, top-10 coins by
  volume, 8 slots, volatility-targeted stakes), simulated with `sim.py` on 41 coins including delisted
  ones. Each result is the median of 10 random coin-priority seeds, as in the news backtest.
* **No look-ahead:** each daily value is used only from the next day on. Open-interest thresholds use
  only earlier data (an expanding quantile), and the first 180 days never fire.
* **Checks:**
  * Every setting is reported, not just the best.
  * Results are split into 2020–23 (2022–23 for open interest) and 2024+.
  * A placebo test runs the same on/off pattern, shifted to random dates. This keeps how often and
    how long the signal fires, but breaks its link to the market.
  * Sizing controls separate "the signal knows something" from "the bot just held more BTC".
* **Data:** Binance only. This cloud environment can't reach DefiLlama, Coin Metrics, Deribit or
  Coinbase, so stablecoin supply, on-chain data, implied volatility and the Coinbase premium are
  not tested. Fear & Greed and funding rates were already rejected in round 2 (see README).

## 1. Altcoins vs BTC

**Idea:** Craider made only +1% in 2025, when altcoins lagged BTC. So the rule holds altcoins only
while an equal-weight basket of the top-10 altcoins, divided by the BTC price, is above its N-day
average. Otherwise only BTC (or BTC and ETH) may be held.

| Variant | 2020–23 | 2024+ | Full | Worst drop |
|---|---|---|---|---|
| **Baseline** | **35.0%** | **20.8%** | **29.3%** | **−23%** |
| Block altcoins + sell them, N = 30…200 (majors = BTC) | 11–16% | 0–16% | 7–12% | −16 to −27% |
| Block altcoin entries only, N = 30…200 (majors = BTC) | 14–17% | 8–14% | 12–16% | −20 to −28% |
| Block altcoin entries only, N = 30…200 (majors = BTC+ETH) | 13–20% | 6–19% | 10–19% | −16 to −25% |

All 20 settings are worse in both periods. The altcoins that pass Craider's own EMA trend check
make money even when the altcoin basket as a whole lags BTC. The coin's own trend already does the
filtering, so a basket-level filter mostly throws away good trades and leaves slots in cash.

**Rotate variant:** block altcoins and give BTC/ETH a 4× stake instead (capped at free cash, no
borrowing).

| Variant | 2020–23 | 2024+ | Full | Worst drop |
|---|---|---|---|---|
| N=30, rotate ×4 | 29.4% | **33.0%** | 31.0% | −24% |
| N=60, rotate ×4 | 29.8% | 29.5% | 29.4% | −32% |
| Placebo (30 random shifts), median, N=30 | — | 21.4% | 26.0% | |
| N=30 real beats placebos | | 97% | 80% | |

The 2024+ result looks strong, but the full period doesn't beat the placebo (it beats only 80% of
them). It also only appears with a 4× stake (with 2× it's 14–22%/yr), and only for N=30. That is
the familiar pattern of something that worked recently and is unlikely to keep working.

## 2. Open interest (leverage build-up)

**Data:** daily BTC open interest in BTC (the total size of open futures bets) from Binance's public
archive (`fetch_oi.py`, Dec 2021 →). **Rule:** the market counts as "hot" while the L-day growth of
open interest is above its q-quantile of all earlier days. It fires 3–9% of the time.

Over 2022-01 → 2026-11 the baseline makes **18.9%/yr with a −24% worst drop**.

| L / q | Block entries | Block + sell all | Half-size entries |
|---|---|---|---|
| 7 / 0.8 | 19.2% | 17.1% | 18.3% |
| 7 / 0.9 | **19.5%** | 20.4% | 18.7% |
| 14 / 0.8 | 19.2% | 17.7% | 19.7% |
| 14 / 0.9 | **19.9%** | 19.4% | 19.4% |
| 30 / 0.8 | 18.8% | 16.3% | 18.3% |
| 30 / 0.9 | 19.3% | 19.7% | 19.1% |

The 18 settings range from −2.6 to +1.5 pp/yr, and worst drops barely move (−18 to −26%). For the
two best "block entries" settings:

| | Real | Placebo median | Placebos ≥ real |
|---|---|---|---|
| L=7, q=0.9 | 19.5% | 18.6% | 8% |
| L=14, q=0.9 | 19.9% | 18.5% | 5% |

So there may be a faint real effect of about +1 pp/yr. But those two settings were chosen from 18,
and that much searching easily produces a 5% placebo result by luck. The data also covers only
about 5 years with one full bull run. It isn't worth the added complexity now. Re-test it with
2027 data.

## Side finding: BTC/ETH weighting

| Stake multiplier | 2020–23 | 2024+ | Full | Worst drop |
|---|---|---|---|---|
| Baseline | 35.0% | 20.8% | 29.3% | −23% |
| BTC/ETH ×1.5 | 39.3% | 24.2% | 33.3% | −24% |
| BTC/ETH ×2 | 43.1% | 27.4% | 36.8% | −25% |
| BTC/ETH ×4 | 53.9% | 28.4% | 41.7% | −29% |
| All coins ×1.5 | 50.5% | 27.4% | 40.1% | −30% |
| All coins ×2 | 58.1% | 23.5% | 43.3% | −35% |

Bigger stakes mean more money invested, so returns and drops both rise. Weighting BTC/ETH up gives
a little more return per unit of drop than weighting everything up. BTC/ETH ×2 makes 36.8%/yr with
a −25% worst drop. All coins ×1.5 makes 40.1%/yr with a −30% worst drop. Much of the gain comes
from 2020 (+135% vs +54% at ×4). This is a choice of how much risk to take, not a signal, and it
should get its own test with Freqtrade's real stake logic before anyone considers it.

## Reproduce

```
cd research
python fetch.py && python fetch2.py && python fetch_oi.py
curl -s 'https://api.alternative.me/fng/?limit=0' -o data/fng.json
python signals_backtest.py alt      # altcoin regime, block variants
python signals_backtest.py rot      # rotate into BTC/ETH
python signals_backtest.py rotctl   # rotate controls + placebo
python signals_backtest.py oi       # open-interest grid
python signals_backtest.py placebo  # open-interest placebo
python signals_backtest.py size     # sizing controls
```
