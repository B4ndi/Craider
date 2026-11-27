# Craider

Crypto trading bot for Binance spot, built on [Freqtrade](https://www.freqtrade.io).

## The strategy: `Craider` (user_data/strategies/Craider.py)

Defensive trend following on 4h candles:
- Trades the 10 most-traded coins (30-day volume) from a list of 35 established coins.
- Buys when EMA50 > EMA200 and price > EMA50; sells when price < EMA100 or after a 20% loss.
- Only holds anything while BTC is above its 200-day average; otherwise all cash.
- Up to 8 positions, each scaled down by the coin's volatility.

Running it: see **[DEPLOY.md](DEPLOY.md)**. A watchdog container (`watchdog/`) sends a Telegram alert if the bot or the Binance connection is down for 10 minutes.

## Research (research/)

Own simulator (`sim.py`, cross-checked against Freqtrade) on 41 coins including collapsed/delisted
ones (LUNA, EOS, XMR, MATIC, FTM) to avoid survivorship bias, 2020-01 → 2026-11.

| | CAGR | Worst drop | Worst year |
|---|---|---|---|
| Hold all 41 coins | 39% | −85% | −76% |
| Hold BTC | ~35% | −77% | −64% |
| Plain EmaTrend, all coins, 4 slots | 92% (but −3%/yr since 2024) | −79% | −64% |
| **Craider** | **29%** | **−23%** | **0%** |

Robustness: 10 alternative EMA settings all give 30–43%/yr with 25–31% drawdown; tripling fees
(slippage) still gives ~28%/yr. Year by year: 2020 +51%, 2021 +67%, 2022 0%, 2023 +32%,
2024 +43%, 2025 +1%, 2026 +22%.

Rejected: tighter stoplosses, trailing stops and a drawdown kill-switch all made results worse;
RSI mean reversion and Donchian breakouts were weaker in 2024+.

### Round 2: other strategy families and sentiment (all on the same 41-coin data)

| Idea | Result | Verdict |
|---|---|---|
| Cross-sectional momentum (hold top 3–5 coins by 2–8 week return) | 14–24%/yr, worst drop 35–41% | Worse than Craider; literature agrees it's weak in crypto |
| Fear & Greed: skip entries when greedy (≥70/80/90) | Returns down up to 12%/yr | Rejected: trend following earns its money in greedy markets |
| Fear & Greed: skip entries when fearful (<25/<40) | +1%/yr | Noise, not adopted |
| Fear & Greed contrarian on BTC (buy panic, sell greed) | Worst year −45% to −64% | Rejected: fear kept deepening in 2022 |
| Funding-rate crowding filter | 0 to −8%/yr | Rejected |
| Funding carry on idle cash (spot long + perp short) | +4%/yr overall, but yield fell to 2.5% (2025) and 1.3% (2026) | Rejected: crowded out, needs futures account |
| BTC only while above 200-day SMA | 32%/yr, worst drop −55% | Simpler but much riskier than Craider |

News: the CyberNews dashboard keeps 30 days of security news, so it can't be backtested, and RSS
news reaches us minutes to hours after prices move. Its best use is a safety alarm (e.g. Binance
hacked or halting withdrawals → stop the bot), not a trading signal.

Reproduce: `cd research && ../.venv/bin/python fetch.py && ../.venv/bin/python fetch2.py && curl -s 'https://api.alternative.me/fng/?limit=0' -o data/fng.json`, then run `final.py`, `run5.py`, `run6.py`.

## Dev usage
```bash
python3 -m venv .venv && .venv/bin/pip install freqtrade
.venv/bin/freqtrade download-data -c user_data/config.json -c user_data/config.backtest.json --timerange 20200101- -t 4h 1d
.venv/bin/freqtrade backtesting -c user_data/config.json -c user_data/config.backtest.json --strategy Craider
```
`config.backtest.json` swaps the volume-based pairlist (live only) for a static list.
`config.sandbox.json` is only for the Claude cloud sandbox, where Binance is geoblocked.
