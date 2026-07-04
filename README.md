# NSE Swing-Trade Screener — Playbook

A free, local, end-of-day screener for the Indian stock market (NSE).
It scans NIFTY 50/100/200/500 stocks with **5 swing-trading strategies**, applies
liquidity filters, and prints a ranked list with a ready-made trade plan
(entry trigger, stop-loss, 2R target) for each candidate.

> Educational tool. Not SEBI-registered investment advice. Paper-trade it for
> 3–4 weeks before using real money.

---

## 1. One-time setup

```powershell
pip install yfinance pandas requests
```

That's it. Data comes free from Yahoo Finance (`.NS` tickers) and the NSE
index-constituent lists (cached locally for 30 days).

## 2. How to run it

Open a terminal in this folder and run:

```powershell
python screener.py                          # NIFTY 200, all 5 strategies (daily default)
python screener.py --universe nifty500      # widest scan (use on weekends)
python screener.py --universe nifty50       # quick 1-minute test run
python screener.py --strategy breakout pullback   # only specific strategies
python screener.py --setups                 # also show squeeze SETUPs (watchlist)
python screener.py --min-turnover 10        # stricter liquidity (₹10 cr/day avg)
python screener.py --notify                 # also send the report to Telegram
python screener.py --auto                   # scheduled-run mode (holiday-aware + notify)
```

Results print to the screen and are saved to `results/scan_<date>.csv`
(open in Excel).

## 3. WHEN to run the screener (IST)

| When | What to run | Why |
|---|---|---|
| **Mon–Fri, 8:00 AM (automated)** | Task Scheduler runs `run_morning_scan.bat` for you | Yesterday's candle is final; results are ready before the 9:15 open so you can place your orders. See "Automation" below. |
| **Mon–Fri, 6:30–9:00 PM (optional manual)** | `python screener.py` | Same signals as next morning's 8 AM run, if you prefer to plan the night before. |
| **Saturday morning** | `python screener.py --universe nifty500 --setups` | Deep weekly scan. Build next week's watchlist from squeeze SETUPs and strong sectors. |
| **Never intraday** | — | Before 3:30 PM the daily candle is incomplete; every signal can vanish by close. |

Routine: **read the 8 AM report → place orders before/at open.** You never
need to watch the market live. 15–20 minutes a day is enough.

## 4. The 5 stock-picking strategies (built into the screener)

All five are long-only, trend-following strategies — the styles that
historically work best in Indian equities, where indices spend most of their
time in uptrends and shorting carries extra friction (SLB, futures margins).

### ① `breakout` — 20-day high breakout with volume
- **Signal:** Close breaks above the last 20 days' high, volume ≥ 1.5× its
  20-day average, green candle, price above the 50- and 200-day averages.
- **Logic:** Institutions leave footprints as volume. A high-volume range
  breakout in an uptrend often runs 5–15% in 5–20 sessions.
- **Best when:** NIFTY itself is above its 50 DMA (bull/recovery phase).

### ② `pullback` — buy the dip to a rising 20 EMA
- **Signal:** Stacked uptrend (20 EMA > 50 SMA > 200 SMA), price pulls back to
  touch the 20 EMA, RSI cools to 35–55, and today prints a green candle.
- **Logic:** You buy a proven uptrend at a discount instead of chasing.
  Usually the **highest win-rate** entry of the five.
- **Best when:** Steady bull market with normal 3–7% dips.

### ③ `momentum` — RSI 60 cross + fresh MACD bullish crossover
- **Signal:** RSI(14) crosses above 60 (within last 3 sessions) while MACD
  makes a fresh bullish crossover, price above 200 SMA, RSI still < 75.
- **Logic:** Two independent momentum confirmations catching a stock as it
  *shifts gears* out of consolidation — earlier than a price breakout.
- **Best when:** Start of a new market up-leg after a correction.

### ④ `near52w` — 52-week-high momentum
- **Signal:** Within 5% of its 52-week high, up ≥ 10% in 3 months, positive
  month, RSI < 80.
- **Logic:** Stocks at new highs have **zero trapped sellers** overhead.
  The classic momentum effect is well documented in Indian equities
  (momentum index/funds exist for a reason).
- **Best when:** Established bull market; leadership sectors.

### ⑤ `squeeze` — volatility contraction breakout (mini-VCP)
- **Signal:** Bollinger Band width in the bottom 15% of the last 6 months
  (energy coiled), then price fires above the upper band / 10-day high on
  volume, above the 200 SMA.
- **Logic:** Volatility cycles: tight, quiet ranges precede explosive moves.
  Run with `--setups` to see coiled stocks *before* they fire — that's your
  watchlist for the coming days.
- **Best when:** Any market; the tightest setups often precede the biggest moves.

**Priority rule:** a stock flagged by **2+ strategies at once** (shown as
`breakout+near52w` etc., sorted to the top) is your strongest candidate.

## 5. How to read the output

| Column | Meaning |
|---|---|
| `Strategies` | Which strategies fired. More = stronger. `(SETUP)` = not yet tradeable, watchlist only. |
| `Close`, `Chg%` | Last close and day's change. |
| `RSI`, `Volx` | RSI(14) and today's volume vs 20-day average. |
| `From52wH%` | Distance below 52-week high (0 = at the high). |
| `Trigger` | **Today's high. Buy next session only if price crosses this.** No cross = no trade — this single rule filters out most failed signals. |
| `Stop` | Initial stop-loss (higher of: 10-day swing low, close − 2×ATR). |
| `Target2R` | Price where reward = 2× risk. Book half here. |
| `Risk%` | Entry-to-stop distance. Over 8% → reduce quantity or skip. |

### Entry mechanics (next morning)
1. Place a **stop-limit / GTT buy** just above `Trigger` (or watch 9:30–10:15
   AM and buy when it crosses — avoid the chaotic 9:15–9:30 open).
2. **Gap rule:** if it opens > 3% above the trigger, skip it. Another bus
   always comes.
3. **Position size:** risk 1% of capital per trade.
   `Qty = (Capital × 0.01) ÷ (Entry − Stop)`. Example: ₹5,00,000 capital,
   entry 500, stop 475 → risk ₹25/share → Qty = 5000/25 = **200 shares**.
4. Max 4–5 open positions; max 2 from the same sector.

## 6. WHEN TO SELL — the 5 exit strategies

Exits matter more than entries. Use all five together:

1. **Initial stop-loss (non-negotiable).** The `Stop` in the output. Enter it
   as a GTT sell the moment your buy fills. Hit = exit fully, no averaging
   down, no "waiting for recovery".
2. **Partial profit at 2R.** At `Target2R`, sell **half**. The trade is now
   risk-free; your worst case is a small win. This is what makes the system
   psychologically survivable.
3. **20 EMA trailing stop (for the rest).** Hold the remaining half while the
   stock **closes** above its 20-day EMA. First daily close below it = exit
   next morning. This lets 20–40% runners run while protecting profits.
4. **Time stop.** Not up at least ~3% after **10 trading sessions**? Exit.
   Dead money kills returns; recycle capital into the next scan's setups.
5. **Event exit (India-specific).** Exit or skip entries **1–2 days before
   quarterly results** of that stock (check the earnings calendar on
   NSE/Moneycontrol). Also exit immediately if the stock enters the
   **ASM/GSM surveillance list** or hits repeated circuit limits.

## 7. India-specific rules & gotchas

- **Trade the trend of the index first.** Only take long setups when NIFTY 50
  is above its 50 DMA. Below it, halve position sizes or sit out — most swing
  losses in India come from fighting a falling index.
- **Avoid:** stocks in ASM/GSM lists, stocks with < ₹5 cr daily turnover
  (the screener filters this), penny stocks < ₹50, and news/operator-driven
  spikes (huge `Volx` with no strategy confluence).
- **Taxes:** swing profits are short-term capital gains (currently 20% for
  equity held < 12 months) plus STT/charges. Factor ~0.2% round-trip costs.
- **Results season** (Jan, Apr, Jul, Oct): expect more gaps; check every
  candidate's results date before entry.
- Yahoo data occasionally misses a fresh listing/rename — a missing symbol or
  two in a 500-stock scan is normal noise.

## 8. Automation — runs itself at 8:00 AM on market days

A Windows scheduled task named **"NSE Swing Screener 8AM"** is already
registered. Every Mon–Fri at 8:00 AM it runs `run_morning_scan.bat`, which:

1. Checks data freshness — if yesterday was an NSE holiday, it exits quietly
   (no stale, duplicate report).
2. Scans NIFTY 200 with all 5 strategies.
3. Checks every position in `holdings.csv` against the exit rules and prints
   SELL/HOLD signals.
4. Saves the CSV to `results/`, writes `logs/last_run.log`, and sends the
   report to your phone via Telegram (once configured — see below).

Notes:
- The task **wakes the PC from sleep**; if the PC was fully shut down, it runs
  as soon as you log in instead.
- The time is your PC's local time — keep the PC clock on IST.
- Manage it in Task Scheduler (search "Task Scheduler" in Start), or:

```powershell
Start-ScheduledTask  -TaskName "NSE Swing Screener 8AM"   # test it now
Disable-ScheduledTask -TaskName "NSE Swing Screener 8AM"  # pause
Enable-ScheduledTask  -TaskName "NSE Swing Screener 8AM"  # resume
Unregister-ScheduledTask -TaskName "NSE Swing Screener 8AM"  # remove
```

## 9. Holdings — automatic SELL signals for your positions

Copy `holdings.sample.csv` to `holdings.csv` and list your open positions
(one row each). Keep it updated as you buy and sell:

```csv
Symbol,BuyDate,BuyPrice,Qty,Stop
RELIANCE,2026-06-15,1280,50,1230
IRCTC,2026-06-25,495,100,470
```

- `Stop` is your stop-loss (from the screener output when you entered).
  Optional but strongly recommended — without it, stop-hit and 2R-target
  signals can't be computed.
- Held stocks outside the scan universe are fetched automatically.

Every scan then prints (and Telegrams) one of these signals per position,
in priority order: **SELL ALL** (stop hit) → **SELL** (closed below 20 EMA)
→ **SELL** (time stop: 10+ sessions, <3% progress) → **BOOK HALF**
(2R target reached) → **HOLD** (with an RSI-80 warning when overheated).

## 10. Get it on your phone (better than an APK)

The reports reach your phone through **Telegram** — free, instant, and it
works like an app without building one. One-time setup (~3 minutes):

1. Install Telegram, search for **@BotFather**, send `/newbot`, follow the
   prompts, and copy the **bot token** it gives you
   (looks like `123456789:AAH9x...`).
2. Search for your new bot by its username and press **Start** (this lets it
   message you).
3. Search for **@userinfobot**, press Start — it replies with your numeric
   **chat id**.
4. Copy `telegram.sample.json` to `telegram.json` and paste both values in.
5. Test: `python screener.py --universe nifty50 --notify` — the report should
   arrive on your phone.

**Why not an actual APK?** The screener needs Python and ~5 minutes of data
downloads; a phone app would have to be awake and online at 8 AM with no OS
battery-killer interference — fragile on Android. Letting the PC (or later, a
free cloud runner) do the work and pushing the result to Telegram gives you
the same "app on my phone" experience with none of those failure modes.

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| NSE list download fails | Cached copy in `cache/` is used automatically; delete it to force refresh. |
| Very slow / rate-limited | Use `--universe nifty200` daily; save `nifty500` for weekends. |
| No results today | Normal. Setups cluster. Never lower the bar just to trade. |
| Symbol errors in console | Renamed/delisted tickers — safe to ignore. |
| 8 AM run didn't happen | PC was off — it runs at next login. Check `logs/last_run.log` and Task Scheduler history. |
| No Telegram message | Check `telegram.json` values; make sure you pressed **Start** on your bot; holiday mornings are silent by design. |
