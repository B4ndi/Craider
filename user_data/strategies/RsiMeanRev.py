"""Mean reversion on 1h candles: buy sharp dips inside an uptrend, sell the bounce."""
import talib.abstract as ta
from pandas import DataFrame
from freqtrade.strategy import IStrategy


class RsiMeanRev(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    startup_candle_count = 210
    minimal_roi = {"0": 100}
    stoploss = -0.08
    process_only_new_candles = True

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["rsi"] = ta.RSI(df, timeperiod=14)
        bb = ta.BBANDS(df, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        df["bb_lower"], df["bb_mid"] = bb["lowerband"], bb["middleband"]
        df["ema200"] = ta.EMA(df, timeperiod=200)
        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[(df["rsi"] < 30) & (df["close"] < df["bb_lower"]) & (df["close"] > df["ema200"]), "enter_long"] = 1
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[(df["rsi"] > 60) | (df["close"] > df["bb_mid"]), "exit_long"] = 1
        return df
