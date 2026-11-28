# Running Craider — step by step

Total cost: about $5/month for the server. Time: ~1 hour the first time.

## 1. Get a server
Rent the cheapest Linux server (Ubuntu 24.04, 1–2 GB RAM) from e.g. Hetzner or DigitalOcean.
**Pick Frankfurt** (or another location in a country Binance serves): Binance blocks servers in the
US and some other countries. Check from the server with
`curl -s -o /dev/null -w '%{http_code}\n' https://api.binance.com/api/v3/ping` (should print 200).
Note its IP address.

## 2. Install the bot
Log in (`ssh root@YOUR_SERVER_IP`) and run:
```bash
curl -fsSL https://get.docker.com | sh
git clone https://github.com/B4ndi/craider.git
cd craider
cp user_data/config.private.example.json user_data/config.private.json
# fill in random passwords for the bot's internal API (used by the watchdog, step 7)
for f in jwt_secret_key ws_token password; do sed -i "s/\"$f\": \"PASTE_[^\"]*\"/\"$f\": \"$(openssl rand -hex 32)\"/" user_data/config.private.json; done
mkdir -p user_data/logs && chown -R 1000:1000 user_data   # the bot runs as user 1000 inside Docker
```

On a server with less than 1 GB RAM, add swap first:
```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## 3. Telegram (to watch and control the bot from your phone)
1. In Telegram, message **@BotFather**, send `/newbot`, follow the steps, copy the **token**.
2. Message **@userinfobot** to get your **chat id**.
3. Put both into `user_data/config.private.json` (`nano user_data/config.private.json`).

## 4. Binance API key
Binance → Profile → API Management → Create API (System generated).
- Enable **Spot & Margin Trading** only. **Never enable withdrawals.**
- Restrict access to your server's IP address.
- Paste key + secret into `user_data/config.private.json`.

## 5. Paper trading (no real money)
```bash
docker compose up -d
```
Telegram should greet you twice: once from the bot, once from the watchdog (step 7). Useful commands: `/status`, `/profit`, `/balance`, `/daily`, `/help`.
Leave `"dry_run": true` for **at least 4 weeks**. Note: the bot only buys while Bitcoin is above
its 200-day average, so it may sit in cash for a while — that is intended.

## Weekly digest on Telegram
Every **Sunday at 18:00 UTC** the bot sends one message with: overall and this week's profit,
open trades, the regime (BTC vs its 200-day average, i.e. whether the bot may buy), the coins it is
watching, and alarms (stoplosses hit, plus errors and Binance warnings from the log).

**Change the schedule** in `user_data/config.json`:
```json
"weekly_digest": {
  "enabled": true,
  "weekday": "sun",
  "hour": 18,
  "timezone": "UTC",
  "send_on_startup": false
}
```
- `weekday`: `mon` … `sun`. `hour`: 0–23. `timezone`: any name like `Europe/Oslo` or `America/New_York`.
- `"enabled": false` turns it off.
- `"send_on_startup": true` sends one digest right after every start; handy to check it works.

Then restart: `docker compose up -d --force-recreate`. The time of the last digest is kept in
`user_data/weekly_digest_state.json`, so restarts don't send duplicates; if the bot was off at the
scheduled time, the missed digest is sent once when it comes back.

## Daily market check on Telegram
Every day at **07:00 UTC** the bot sends a short message so you can see it is alive and why it is
or isn't trading:
- trading capital and profit, open trades, what it bought and sold in the last 24 hours;
- **Can it buy?** BTC versus its 200-day average, and how far BTC has to rise before buying starts;
- every watched coin with how many of the 3 buy rules it meets (uptrend = EMA50 above EMA200,
  price above EMA50, price above EMA100) and how far it is from the missing ones.

The first one is sent right after you deploy this; after that once a day. Separately, the moment BTC
closes a day **above** its 200-day average you get 🟢 "may buy again" (and 🔴 when it drops below,
which is when the bot sells and goes to cash). Every paper buy and sell is announced by Freqtrade
itself as before. Change the time in `config.json`:

```json
"market_check": {
  "enabled": true,
  "hour": 7,
  "timezone": "UTC",
  "send_on_startup": false,
  "regime_alerts": true
}
```

## 6. Going live
Only when paper trading ran without errors:
1. Put the money you're prepared to lose into your Binance spot wallet as **USDT**.
   Start small (e.g. $200–500). The bot can use the whole USDT balance in the account.
2. Set `"dry_run": false` in `user_data/config.private.json`.
3. `docker compose up -d --force-recreate`

## 7. Health alerts (watchdog)
The bot is silent while it sits in cash, which can last months. So you can tell "quiet" from
"dead", a second small container (`craider-watchdog`, code in `watchdog/`) checks every minute:

| Check | Alerts when |
|---|---|
| **bot** | the bot container is down or crashed, its main loop has not finished a cycle for 3+ min (stuck), or it is stopped (`/stop` or a fatal error) |
| **exchange** | Binance can't be reached from the server, or Binance rejects your API key (expired, deleted, server IP not on its allow list). Without a real key it only checks reachability. |

A problem must last **10 minutes** before you get a Telegram message (🚨), so restarts and short
blips stay quiet. While it lasts you get a reminder (⏰) every **6 hours**, and a ✅ when it clears.
**No message means everything is fine.** It uses the same Telegram bot and chat as the bot itself.
`/stopentry` (paused) does not count as a problem; `/stop` does, so you get a reminder every 6 hours
until you `/start` again.

It starts with `docker compose up -d` (step 5); nothing else to do if you followed step 2.

**Test it once:** `docker stop craider`, wait ~11 minutes for the 🚨 message, then
`docker start craider` and wait for the ✅.

**If the whole server dies** nothing on it can send a message. To cover that too (optional, free):
1. Sign up at [healthchecks.io](https://healthchecks.io), create a check with period **5 minutes**
   and grace **10 minutes**, and connect Telegram under *Integrations*.
2. Put its ping URL into a file `.env` next to `docker-compose.yml`:
   `echo 'HEALTHCHECK_URL=https://hc-ping.com/your-uuid' > .env`
3. `docker compose up -d`

The watchdog pings that URL every minute while all is well (and `/fail` once a problem passes 10
minutes), so healthchecks.io messages you when the pings stop or fail.

**Tuning** (optional, also in `.env`): `WATCHDOG_DOWN_MINUTES=10`, `WATCHDOG_REMIND_HOURS=6`,
`WATCHDOG_CHECK_SECONDS=60`. Then `docker compose up -d`.

**Watchdog logs:** `docker logs --tail 50 craider-watchdog`. If it says the config is missing
`api_server`, do the upgrade steps below.

**Upgrading an existing install** (set up before the watchdog existed):
```bash
cd craider && git pull
nano user_data/config.private.json   # add the "api_server" block from config.private.example.json
for f in jwt_secret_key ws_token password; do sed -i "s/\"$f\": \"PASTE_[^\"]*\"/\"$f\": \"$(openssl rand -hex 32)\"/" user_data/config.private.json; done
docker compose up -d --force-recreate
```
The bot's API listens only on Docker's internal network; no port is opened on the server.

## Emergency
- `/stopentry` — stop buying, keep managing open trades.
- `/forceexit all` — sell everything now.
- `/stop` — stop the bot (stoplosses stay on Binance). The watchdog reminds you every 6 hours.
- Or on the server: `cd craider && docker compose down` (stops the watchdog too; pause the
  healthchecks.io check first if you use one).

## What to expect
Backtest 2020–Nov 2026 (41 coins incl. collapsed ones like LUNA): ~29%/yr, worst drop −23%,
no losing calendar year. It **will** lag far behind in strong bull years and has long dull stretches.
Live results are usually worse than backtests. A loss of 25–35% from peak is entirely possible.
