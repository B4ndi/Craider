"""
Craider: defensive trend following on Binance spot (4h candles).

Rules (all researched in research/; see README):
  * Universe   - the 10 most-traded coins (30-day volume) out of a list of established coins.
  * Entry      - EMA50 > EMA200 and close > EMA50, and BTC's daily close is above its 200-day SMA.
  * Exit       - close < EMA100, or BTC falls below its 200-day SMA (go to cash), or -20% stoploss.
  * Sizing     - up to 8 positions; each position scaled down by the coin's volatility so a
                 wild coin gets a smaller stake (target 40% annualized vol per slot).

Telegram: a weekly digest (weekly_digest.py), a daily market check that shows why the bot is or
isn't buying, and an instant alert when BTC crosses its 200-day average (market_check.py).
Schedules in config.json, see DEPLOY.md.
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import talib.abstract as ta
from pandas import DataFrame
from freqtrade.enums import RunMode
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, merge_informative_pair

import market_check
import weekly_digest

logger = logging.getLogger(__name__)


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

    def bot_start(self, **kwargs) -> None:
        self.digest = self.daily = self.regime_watch = None
        self._regime_day = None
        if self.dp.runmode not in (RunMode.DRY_RUN, RunMode.LIVE):
            return  # no Telegram reports in backtesting / hyperopt
        user_dir = Path(self.config["user_data_dir"])
        cfg = weekly_digest.settings(self.config)
        self.digest = weekly_digest.DigestSchedule(cfg, user_dir / weekly_digest.STATE_FILE)
        mcfg = market_check.settings(self.config)
        self.daily = market_check.DailySchedule(mcfg, user_dir / market_check.STATE_FILE)
        if mcfg["regime_alerts"]:
            self.regime_watch = market_check.RegimeWatch(user_dir / market_check.REGIME_FILE)

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        self._check_regime()
        self._send_daily_check(current_time)
        self._send_weekly_digest(current_time)

    def _btc_regime(self) -> tuple[dict | None, object]:
        btc = self.dp.get_pair_dataframe("BTC/USDT", "1d")
        if len(btc) < 200:
            return None, None
        regime = {
            "btc": float(btc["close"].iloc[-1]),
            "sma200": float(btc["close"].rolling(200).mean().iloc[-1]),
        }
        return regime, btc["date"].iloc[-1] if "date" in btc else len(btc)

    def _check_regime(self) -> None:
        if getattr(self, "regime_watch", None) is None:
            return
        try:
            regime, day = self._btc_regime()
            if regime is None or day == self._regime_day:
                return  # only look again when a new daily candle arrives
            self._regime_day = day
            flipped = self.regime_watch.update(regime["btc"] > regime["sma200"])
            if flipped is not None:
                n_open = len(Trade.get_trades_proxy(is_open=True))
                text = market_check.compose_regime_alert(flipped, regime, n_open)
                logger.info("Regime changed:\n%s", text)
                self.dp.send_msg(text, always_send=True)
        except Exception:
            logger.exception("Regime alert failed")

    def _send_daily_check(self, now: datetime) -> None:
        daily = getattr(self, "daily", None)
        if daily is None or not daily.is_due(now):
            return
        try:
            data = self._daily_data(now)
        except Exception:
            logger.exception("Daily market check failed; will try again tomorrow")
            daily.mark_sent(now)
            return
        # Right after a start, bot_loop_start runs before the first analysis: wait for the
        # coin data (a few seconds), but never more than 10 minutes.
        if not data["coins"] and self.dp.current_whitelist():
            self._daily_wait_since = getattr(self, "_daily_wait_since", None) or now
            if now - self._daily_wait_since < timedelta(minutes=10):
                return
        self._daily_wait_since = None
        try:
            text = market_check.compose(data)
            logger.info("Sending daily market check:\n%s", text)
            self.dp.send_msg(text, always_send=True)
        except Exception:
            logger.exception("Daily market check failed; will try again tomorrow")
        finally:
            daily.mark_sent(now)

    def _daily_data(self, now: datetime) -> dict:
        day_ago = now - timedelta(days=1)
        open_trades, unrealized = self._open_trades(now)
        closed = Trade.get_trades_proxy(is_open=False)
        coins = []
        for pair in self.dp.current_whitelist():
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if df.empty or not {"ema50", "ema100", "ema200"} <= set(df.columns):
                continue
            row = df.iloc[-1]
            if any(np.isnan(row[c]) for c in ("close", "ema50", "ema100", "ema200")):
                continue
            coins.append({"pair": pair, **market_check.coin_status(
                float(row["close"]), float(row["ema50"]), float(row["ema100"]), float(row["ema200"]))})
        regime, _ = self._btc_regime()
        return {
            "stake": self.config["stake_currency"],
            "dry_run": self.config["dry_run"],
            "starting_balance": self.wallets.get_starting_balance() if self.wallets else 0.0,
            "realized_total": Trade.get_total_closed_profit(),
            "unrealized": unrealized,
            "open_trades": open_trades,
            "max_open_trades": self.config["max_open_trades"],
            "closed_count": len(closed),
            "bought_24h": [t.pair for t in Trade.get_trades_proxy()
                           if t.open_date_utc and t.open_date_utc >= day_ago],
            "sold_24h": [{"pair": t.pair, "profit_pct": (t.close_profit or 0.0) * 100}
                         for t in closed if t.close_date_utc and t.close_date_utc >= day_ago],
            "regime": regime,
            "coins": coins,
        }

    def _open_trades(self, now: datetime) -> tuple[list, float]:
        open_trades = []
        unrealized = 0.0
        for t in Trade.get_trades_proxy(is_open=True):
            rate = self._current_rate(t.pair, t.open_rate)
            profit_abs = t.calc_profit(rate)
            unrealized += profit_abs
            open_trades.append({
                "pair": t.pair,
                "profit_abs": profit_abs,
                "profit_pct": t.calc_profit_ratio(rate) * 100,
                "days": (now - t.open_date_utc).total_seconds() / 86400,
            })
        return open_trades, unrealized

    def _send_weekly_digest(self, current_time: datetime) -> None:
        digest = getattr(self, "digest", None)
        if digest is None or not digest.is_due(current_time):
            return
        try:
            text = weekly_digest.compose(self._digest_data(current_time))
            logger.info("Sending weekly digest:\n%s", text)
            self.dp.send_msg(text, always_send=True)
        except Exception:
            logger.exception("Weekly digest failed; will try again at the next scheduled time")
        finally:
            digest.mark_sent(current_time)  # never retry every loop, even after an error

    def _current_rate(self, pair: str, fallback: float) -> float:
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if not df.empty:
            return float(df["close"].iloc[-1])
        try:
            return float(self.dp.ticker(pair)["last"])
        except Exception:
            return fallback

    def _digest_data(self, now: datetime) -> dict:
        week_ago = now - timedelta(days=7)
        open_trades, unrealized = self._open_trades(now)
        week_closed = [
            {
                "pair": t.pair,
                "profit_abs": t.close_profit_abs or 0.0,
                "profit_pct": (t.close_profit or 0.0) * 100,
                "exit_reason": t.exit_reason,
            }
            for t in Trade.get_trades_proxy(is_open=False, close_date=week_ago)
        ]
        regime, _ = self._btc_regime()
        total, top = weekly_digest.read_alarms(self.config.get("logfile"), week_ago)
        return {
            "stake": self.config["stake_currency"],
            "dry_run": self.config["dry_run"],
            "starting_balance": self.wallets.get_starting_balance() if self.wallets else 0.0,
            "realized_total": Trade.get_total_closed_profit(),
            "unrealized": unrealized,
            "week_closed": week_closed,
            "open_trades": open_trades,
            "max_open_trades": self.config["max_open_trades"],
            "whitelist": self.dp.current_whitelist(),
            "regime": regime,
            "alarms_total": total,
            "alarms": top,
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
