"""
Craider: defensive trend following on Binance spot (4h candles).

Rules (all researched in research/; see README):
  * Universe   - the 10 most-traded coins (30-day volume) out of a list of established coins.
  * Entry      - EMA50 > EMA200 and close > EMA50, and BTC's daily close is above its 200-day SMA.
  * Exit       - close < EMA100, or BTC falls below its 200-day SMA (go to cash), or -20% stoploss.
  * Sizing     - up to 8 positions; each position scaled down by the coin's volatility so a
                 wild coin gets a smaller stake (target 40% annualized vol per slot).
"""
import numpy as np
import talib.abstract as ta
from pandas import DataFrame
from freqtrade.strategy import IStrategy, merge_informative_pair


class Craider(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "4h"
    startup_candle_count = 220
    minimal_roi = {"0": 100}          # no fixed take-profit: ride trends
    stoploss = -0.20
    process_only_new_candles = True
    use_exit_signal = True

    target_vol = 0.40                 # per-slot annualized volatility target

    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "limit",
        "stoploss_on_exchange": True,  # stop lives on Binance: protects even if the bot is offline
        "stoploss_on_exchange_limit_ratio": 0.98,
    }

    def informative_pairs(self):
        return [("BTC/USDT", "1d")]

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["ema50"] = ta.EMA(df, timeperiod=50)
        df["ema100"] = ta.EMA(df, timeperiod=100)
        df["ema200"] = ta.EMA(df, timeperiod=200)
        df["vol"] = df["close"].pct_change().rolling(180, min_periods=60).std() * np.sqrt(6 * 365)
        btc = self.dp.get_pair_dataframe("BTC/USDT", "1d").copy()
        btc["btc_bull"] = (btc["close"] > btc["close"].rolling(200).mean()).astype(int)
        return merge_informative_pair(df, btc[["date", "btc_bull"]], self.timeframe, "1d", ffill=True)

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[
            (df["ema50"] > df["ema200"])
            & (df["close"] > df["ema50"])
            & (df["close"] >= df["ema100"])
            & (df["btc_bull_1d"] == 1),
            "enter_long",
        ] = 1
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[(df["close"] < df["ema100"]) | (df["btc_bull_1d"] != 1), "exit_long"] = 1
        return df

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake,
                            min_stake, max_stake, leverage, entry_tag, side, **kwargs) -> float:
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df.empty or np.isnan(df["vol"].iloc[-1]) or df["vol"].iloc[-1] <= 0:
            return proposed_stake
        slots = self.config["max_open_trades"]
        per_slot = self.wallets.get_total_stake_amount() / slots
        return min(proposed_stake, per_slot * self.target_vol / df["vol"].iloc[-1], max_stake)
