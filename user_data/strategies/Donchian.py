"""Classic 'turtle' breakout on daily candles: buy a 20-day high, sell a 10-day low."""
from pandas import DataFrame
from freqtrade.strategy import IStrategy


class Donchian(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    startup_candle_count = 30
    minimal_roi = {"0": 100}
    stoploss = -0.25
    process_only_new_candles = True

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["hi20"] = df["high"].rolling(20).max().shift(1)
        df["lo10"] = df["low"].rolling(10).min().shift(1)
        return df

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[df["close"] > df["hi20"], "enter_long"] = 1
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[df["close"] < df["lo10"], "exit_long"] = 1
        return df
