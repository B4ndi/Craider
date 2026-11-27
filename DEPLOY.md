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
Telegram should greet you. Useful commands: `/status`, `/profit`, `/balance`, `/daily`, `/help`.
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

## 6. Going live
Only when paper trading ran without errors:
1. Put the money you're prepared to lose into your Binance spot wallet as **USDT**.
   Start small (e.g. $200–500). The bot can use the whole USDT balance in the account.
2. Set `"dry_run": false` in `user_data/config.private.json`.
3. `docker compose up -d --force-recreate`

## Emergency
- `/stopentry` — stop buying, keep managing open trades.
- `/forceexit all` — sell everything now.
- `/stop` — stop the bot (stoplosses stay on Binance).
- Or on the server: `cd craider && docker compose down`.

## What to expect
Backtest 2020–Nov 2026 (41 coins incl. collapsed ones like LUNA): ~29%/yr, worst drop −23%,
no losing calendar year. It **will** lag far behind in strong bull years and has long dull stretches.
Live results are usually worse than backtests. A loss of 25–35% from peak is entirely possible.
