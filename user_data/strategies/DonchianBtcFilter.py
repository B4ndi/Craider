"""Donchian breakout, but only takes new trades while BTC is above its 200-day average."""
from pandas import DataFrame
from freqtrade.strategy import IStrategy, merge_informative_pair


class DonchianBtcFilter(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1d"
    startup_candle_count = 210
    minimal_roi = {"0": 100}
    stoploss = -0.25
    process_only_new_candles = True

    def informative_pairs(self):
        return [("BTC/USDT", "1d")]

    def populate_indicators(self, df: DataFrame, metadata: dict) -> DataFrame:
        df["hi20"] = df["high"].rolling(20).max().shift(1)
        df["lo10"] = df["low"].rolling(10).min().shift(1)
        btc = self.dp.get_pair_dataframe("BTC/USDT", "1d").copy()
        btc["btc_bull"] = (btc["close"] > btc["close"].rolling(200).mean()).astype(int)
        return merge_informative_pair(df, btc[["date", "btc_bull"]], self.timeframe, "1d", ffill=True)

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[(df["close"] > df["hi20"]) & (df["btc_bull_1d"] == 1), "enter_long"] = 1
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[df["close"] < df["lo10"], "exit_long"] = 1
        return df
