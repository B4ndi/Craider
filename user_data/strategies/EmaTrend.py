"""Trend following on 4h candles: hold while price is above a rising long-term trend."""
import talib.abstract as ta
from pandas import DataFrame
from freqtrade.strategy import IStrategy


class EmaTrend(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "4h"
    startup_candle_count = 210
    minimal_roi = {"0": 100}  # no fixed take-profit; exits come from the trend breaking
    stoploss = -0.20
    process_only_new_candles = True

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["ema50"] = ta.EMA(df, timeperiod=50)
        df["ema100"] = ta.EMA(df, timeperiod=100)
        df["ema200"] = ta.EMA(df, timeperiod=200)
        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[(df["ema50"] > df["ema200"]) & (df["close"] > df["ema50"]), "enter_long"] = 1
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[df["close"] < df["ema100"], "exit_long"] = 1
        return df
