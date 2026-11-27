# Do cybersecurity-news exits improve Craider?

**Conclusion: no, not as a trading rule.** Selling everything when security news breaks does not
reliably improve Craider's returns or drawdowns over 2020-01 → 2026-11. The narrow alarm the README
proposes (Binance compromised, USDT depeg, a top-5 exchange hacked or halting) is close to free, but
it also adds almost nothing in price terms (+0.0 to +1.0 pp/yr), because it fired only 3 times while
the bot was invested. Keep it only as an operational safety switch, not as a source of return. A broad
alarm on every exchange or DeFi hack is noise with short pauses (−1.9 to +2.0 pp/yr). With long
pauses it looks good (+3.6 to +5.1 pp/yr), but all of that gain comes from 2024 onward. It is the best
of 32 settings, and single incidents swing the result by up to ±12%, so it is not trustworthy yet.

Live trading is unchanged by this work. The script only adds an optional `halt` argument to the
research simulator (`sim.py`), and that argument is off by default.

## Method

* **Strategy:** the live Craider rules, simulated with `sim.py` on 41 coins including delisted ones,
  with the median of 10 random coin-priority seeds. The baseline reproduces the README: **29.3%/yr,
  −23.2% worst drop, worst year 0%**.
* **Incidents:** [`incidents.csv`](incidents.csv) lists 42 hand-curated incidents from 2020-09 to 2026-10,
  each with the approximate UTC time the news became public.
  * **Tier A (6 incidents)** are the README's "stop the bot" cases: the USDT depegs (May 2022 and
    a minor one in June 2023), the BNB Chain bridge hack (Oct 2022), the FTX withdrawal halt
    (Nov 2022), the Bybit hack (Feb 2025) and the Binance hot-wallet hack (Oct 29 2026, about $6.3B).
  * **Tier B (36 incidents)** is everything else a keyword alarm would catch: other exchange hacks
    and halts (KuCoin, Celsius, WazirX, Bitget …), large DeFi and bridge hacks, and other stablecoin
    depegs (UST, USDC, USDe).
  * The archived CyberNews feed only covers 30 days, so this list stands in for it. Times are
    approximate to a few hours, which is why the backtest adds an extra delay of 0–24h.
* **News exit:** at news time plus the delay, every position is sold at the next 4h open. No new
  entries are taken for a pause of 1–14 days, and after that the normal Craider rules re-enter.
* **Checks:**
  * A placebo test that puts the same number of alarms at random moments in bull markets. Hacks
    cluster in bear markets, when Craider is in cash anyway, so random times over the whole period
    would not be a fair comparison.
  * An event study of what prices did after each alarm.
  * The effect of each incident on its own.
  * A split into 2020–2023 and 2024 onward.

## Results

### Most alarms never touch the bot

Of 42 incidents, only **19 hit while Craider held coins**. The other 23 hit when BTC was below its
200-day average, mostly during the 2022 crash, so the bot was already in cash. The trend filter is
already the "panic" exit: Terra, Celsius, FTX and the 2022 USDT depeg all happened while the bot was
out of the market.

### Prices don't reliably fall after the news

BTC return after the first 4h open following the news:

| Horizon | Tier A (median) | All incidents (median) | Any random moment (median) |
|---|---|---|---|
| 4h | +0.4% | 0.0% | 0.0% |
| 1 day | 0.0% | −0.2% | +0.1% |
| 3 days | −0.4% | +0.4% | +0.2% |
| 7 days | −1.9% | +0.9% | +0.4% |

The top-10 coin basket Craider actually trades, after the 24 alarms that fell in bull markets, compared with
2,000 random sets of 24 bull-market moments:

| Horizon | After alarms | Random | Random draws that were lower |
|---|---|---|---|
| 1 day | +1.4% | +0.3% | 92% |
| 3 days | +1.6% | +0.7% | 74% |
| 7 days | +1.3% | +1.6% | 45% |
| 14 days | −1.0% | +3.1% | 10% |

The first days after a hack are, if anything, slightly *up*, so selling immediately is wrong-footed.
There is a weak hint that coins lag over the following two weeks, but 10% of random draws were worse
still (p ≈ 0.10), so it is not significant.

### Strategy results: change in CAGR versus 29.3%/yr baseline (median of 10 seeds)

Tier A only (the README's proposed alarm):

| Delay \ pause | 1d | 3d | 7d | 14d |
|---|---|---|---|---|
| 0h | +0.1 | +0.2 | +0.4 | +0.8 |
| 4h | +0.0 | +0.2 | +0.3 | +0.7 |
| 12h | +0.0 | +0.3 | +0.3 | +1.0 |
| 24h | +0.1 | +0.3 | +0.3 | +0.5 |

The worst drop improves by 0 to 1.8 pp. Tier A only mattered 3 times (Bybit, Binance 2026, and the
small 2023 USDT wobble), and in the placebo test the real tier A alarms beat only 60% of random ones.
That is harmless, but it is not evidence of an edge.

All incidents (tier A and B):

| Delay \ pause | 1d | 3d | 7d | 14d |
|---|---|---|---|---|
| 0h | −1.3 | −0.2 | +1.6 | +3.9 |
| 4h | −1.8 | +0.3 | +2.0 | +3.7 |
| 12h | −1.9 | +0.4 | +1.6 | +3.6 |
| 24h | +0.9 | +2.0 | +3.7 | +5.1 |

Worst drop changes range from −2.0 to +3.0 pp.

The long-pause column is the only place this looks promising. Here is why it is not adopted:

1. **It all comes from 2024 onward.** For the best cell (24h delay, 14-day pause), 2020–2023
   returns *fall* from 35.0 to 34.1%/yr, while 2024 onward returns jump from 20.8 to 35.2%/yr. 2024–2026 was choppy
   for trend following (2025: +1%), and sitting out two weeks at a time helped regardless of cause.
2. **Single events dominate, with random signs.** With a 24h delay and 14-day pause (one incident at a time; the script prints the same table for 4h/3d, where it ranges from −6.8% to +3.1%), the HTX hack (Nov 2023)
   alone cost 12.7% of final equity and Liquid (Aug 2021) cost 8.8%, while Orbit (Jan 2024) added 6.8% and
   Bitget (Sep 2026) added 6.4%. Exiting and re-entering also reshuffles which coins fill the slots.
   That path dependence is large compared with any real effect.
3. **Selection bias.** It is the best of 32 settings. Against random bull-market alarms it beats 98% of
   them, but random 14-day pauses are costly (median 22.8%/yr), and with 32 tries one cell at the 98th
   percentile is expected. The pre-registered default (4h delay, 3-day pause) beats only 78%.
4. **No mechanism.** The event study shows no reliable price drop after the news (see above).

### Placebo summary (fixed coin order, 200 random draws inside bull markets)

| Setting | Real alarms | Random alarms (median, 5–95%) | Real beats |
|---|---|---|---|
| All incidents, 4h delay, 3d pause | 28.6%/yr | 26.4% (21.4–31.4%) | 78% |
| Tier A, 4h delay, 3d pause | 29.5%/yr | 29.3% (27.2–30.6%) | 60% |
| All incidents, 24h delay, 14d pause (best of grid) | 33.8%/yr | 22.8% (14.2–30.6%) | 98% |

## Recommendation

1. **Don't add news-driven exits to the strategy.** The trend filter already handles the systemic
   crashes (2022), and the rest is noise.
2. **Keep the narrow tier-A alarm as an operational kill switch**, for example a Telegram alert plus
   `/stopentry` or `/forceexit` when Binance itself is compromised or USDT depegs. It costs nothing in
   backtest terms, and its real value is counterparty risk, which a price backtest cannot measure. One
   caveat: selling to USDT *on Binance* does not protect funds held on Binance. In the Oct 2026 hack,
   withdrawals were suspended for four weeks. If that risk matters, the response is moving funds off
   the exchange, not selling.
3. **Re-test the long-pause variant on 2027 data** before acting on it. If it only works in 2024–2026,
   it was luck.

## Limitations

* The incident list is hand-curated from public reporting and its times are approximate. Incidents
  in 2026 were checked against news coverage, and earlier ones come from well-known records. A
  bigger or differently chosen list could change the tier B numbers.
* The simulation fills at 4h candle opens. It does not model a crash within the candle or Binance
  matching-engine problems during an incident.
* Price data starts in 2020, so there are few tier A events (6 in total, 3 while invested).

## Reproduce

```bash
cd research
python fetch.py && python fetch2.py
curl -s 'https://api.alternative.me/fng/?limit=0' -o data/fng.json
python news_backtest.py        # about 5 minutes; full output also saved to data/news_backtest.json
```
