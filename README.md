# Craider

Crypto trading bot for Binance spot, built on [Freqtrade](https://www.freqtrade.io).

## Strategies (`user_data/strategies/`)

| Strategy | Timeframe | Idea |
|---|---|---|
| `EmaTrend` | 4h | Hold while close > EMA50 > EMA200; exit below EMA100 |
| `Donchian` | 1d | Buy 20-day high breakout, sell 10-day low |
| `DonchianBtcFilter` | 1d | Donchian, but only enter while BTC is above its 200-day SMA |
| `RsiMeanRev` | 1h | Buy RSI<30 dips below lower Bollinger band in an uptrend |

## Backtest results (10 major USDT pairs, 0.1% fee, $1000 start, 4 slots)

| | 2020–2023 | DD | 2024–Nov 2026 | DD |
|---|---|---|---|---|
| EmaTrend | +1147% | 58% | **+109%** | **28%** |
| Donchian | +1556% | 71% | +2% | 59% |
| DonchianBtcFilter | +2128% | 51% | +59% | 39% |
| RsiMeanRev | +12% | 17% | −7% | 10% |
| BTC buy & hold | +514% | 77% | +37% | 53% |
| Equal-weight buy & hold | +1458% | 86% | −19% | 68% |

Parameters are textbook defaults, not optimized. Caveat: the pair list is today's
large caps, so results carry survivorship bias.

## Usage

```bash
python3 -m venv .venv && .venv/bin/pip install freqtrade
.venv/bin/freqtrade download-data -c user_data/config.json --timerange 20200101- -t 1h 4h 1d
.venv/bin/freqtrade backtesting -c user_data/config.json --strategy EmaTrend
.venv/bin/freqtrade trade -c user_data/config.json --strategy EmaTrend   # dry_run by default
```

`user_data/config.sandbox.json` is only for the Claude cloud sandbox (Binance is
geoblocked there); don't use it on a real server. Put API keys in a separate,
uncommitted `config.private.json` and pass it as an extra `-c`.
