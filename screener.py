#!/usr/bin/env python3
"""NSE swing-trade screener - 5 strategies for the Indian stock market.

Manual runs:

    python screener.py                            # NIFTY 200, all 5 strategies
    python screener.py --universe nifty500 --setups
    python screener.py --strategy breakout pullback

Scheduled morning run (used by run_morning_scan.bat + Task Scheduler, 8 AM):

    python screener.py --auto     # skips NSE holidays, sends Telegram report

Holdings: copy holdings.sample.csv to holdings.csv and list your open
positions - every scan will then print SELL/HOLD signals for them.

Phone alerts: copy telegram.sample.json to telegram.json and fill in your
bot token + chat id (see README, "Get it on your phone").

See README.md for the full playbook. Educational tool only - not investment advice.
"""

import argparse
import io
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
RESULTS_DIR = BASE_DIR / "results"

INDEX_URLS = {
    "nifty50": "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    "nifty100": "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
    "nifty200": "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
    "nifty500": "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
}

# Used only if the NSE constituent list cannot be downloaded and no cache exists.
FALLBACK_NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY",
    "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN",
    "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]

STRATEGY_INFO = {
    "breakout":  "20-day high breakout on 1.5x volume, in an uptrend",
    "pullback":  "Dip to a rising 20 EMA inside an uptrend (buy the dip)",
    "momentum":  "RSI crosses 60 + fresh MACD bullish crossover",
    "near52w":   "Within 5% of 52-week high with strong 3-month momentum",
    "squeeze":   "Volatility contraction (Bollinger squeeze) firing a breakout",
}


# --------------------------------------------------------------------------- #
# Universe
# --------------------------------------------------------------------------- #

def get_universe(name: str) -> list[str]:
    """Return NSE symbols for the chosen index, cached locally for 30 days."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"{name}.csv"

    fresh = cache.exists() and (
        datetime.now().timestamp() - cache.stat().st_mtime < 30 * 86400
    )
    if not fresh:
        try:
            resp = requests.get(
                INDEX_URLS[name],
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=20,
            )
            resp.raise_for_status()
            cache.write_bytes(resp.content)
        except Exception as exc:
            print(f"! Could not download {name} list from NSE ({exc}).")
            if not cache.exists():
                print("! Falling back to built-in NIFTY 50 list.")
                return FALLBACK_NIFTY50
            print("! Using previously cached list.")

    df = pd.read_csv(io.BytesIO(cache.read_bytes()))
    return sorted(df["Symbol"].astype(str).str.strip().unique().tolist())


# --------------------------------------------------------------------------- #
# Data + indicators
# --------------------------------------------------------------------------- #

def fetch_history(symbols: list[str], period: str = "15mo") -> dict[str, pd.DataFrame]:
    """Download daily OHLCV from Yahoo Finance (NSE = '.NS' suffix)."""
    frames: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), 100):
        chunk = symbols[i : i + 100]
        tickers = [s + ".NS" for s in chunk]
        data = None
        for attempt in (1, 2):  # one retry - cloud runners hit occasional 429s
            data = yf.download(
                tickers, period=period, interval="1d", group_by="ticker",
                auto_adjust=True, threads=True, progress=False,
            )
            if data is not None and not data.empty:
                break
            time.sleep(10)
        if data is None or data.empty:
            continue
        multi = isinstance(data.columns, pd.MultiIndex)
        for sym, tk in zip(chunk, tickers):
            try:
                df = data[tk] if multi else data
            except KeyError:
                continue
            df = df.dropna(how="all")
            # 60 bars is enough for holdings checks; the scan itself still
            # requires a valid SMA200 (~200 bars) before flagging a stock.
            if len(df) >= 60:
                frames[sym] = df
        print(f"  downloaded {min(i + 100, len(symbols))}/{len(symbols)} symbols "
              f"({len(frames)} usable)")
    return frames


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c, h, lo, v = d["Close"], d["High"], d["Low"], d["Volume"]

    d["SMA50"] = c.rolling(50).mean()
    d["SMA200"] = c.rolling(200).mean()
    d["EMA20"] = c.ewm(span=20, adjust=False).mean()

    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14).mean()
    d["RSI"] = 100 - 100 / (1 + gain / loss)

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    d["MACD"] = ema12 - ema26
    d["MACDSig"] = d["MACD"].ewm(span=9, adjust=False).mean()

    prev_c = c.shift(1)
    tr = pd.concat([h - lo, (h - prev_c).abs(), (lo - prev_c).abs()], axis=1).max(axis=1)
    d["ATR"] = tr.ewm(alpha=1 / 14, min_periods=14).mean()

    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    d["BBUpper"] = mid + 2 * sd
    d["BBWidth"] = (4 * sd) / mid

    d["VolAvg20"] = v.rolling(20).mean().shift(1)  # excludes today
    d["VolRatio"] = v / d["VolAvg20"]
    d["Turnover20"] = (c * v).rolling(20).mean()   # rupees/day

    return d


# --------------------------------------------------------------------------- #
# Strategies - each returns (hit, score, status) for the LAST completed bar
# --------------------------------------------------------------------------- #

def s_breakout(d: pd.DataFrame):
    t = d.iloc[-1]
    hi20_prev = d["High"].iloc[-21:-1].max()
    hit = (
        t.Close > hi20_prev
        and t.VolRatio >= 1.5
        and t.Close > t.Open
        and t.Close > t.SMA200
        and t.SMA50 > t.SMA200
    )
    return hit, float(t.VolRatio), "FIRED"


def s_pullback(d: pd.DataFrame):
    t = d.iloc[-1]
    hit = (
        t.EMA20 > t.SMA50 > t.SMA200
        and t.Close > t.SMA200
        and t.Low <= t.EMA20 * 1.02
        and t.Close >= t.EMA20 * 0.97
        and 35 <= t.RSI <= 55
        and t.Close > t.Open
    )
    score = 100 - abs(t.Close / t.EMA20 - 1) * 1000  # closer to EMA = better
    return hit, float(score), "FIRED"


def s_momentum(d: pd.DataFrame):
    t = d.iloc[-1]
    rsi = d["RSI"]
    crossed_60 = t.RSI >= 60 and (rsi.iloc[-4:-1] < 60).any()
    hist = d["MACD"] - d["MACDSig"]
    macd_fresh_cross = t.MACD > t.MACDSig and (hist.iloc[-6:-1] <= 0).any()
    hit = crossed_60 and macd_fresh_cross and t.Close > t.SMA200 and t.RSI < 75
    return hit, float(t.RSI), "FIRED"


def s_near52w(d: pd.DataFrame):
    t = d.iloc[-1]
    hi52 = d["High"].iloc[-252:].max()
    ret_3m = t.Close / d["Close"].iloc[-64] - 1
    ret_1m = t.Close / d["Close"].iloc[-22] - 1
    hit = (
        t.Close >= 0.95 * hi52
        and ret_3m >= 0.10
        and ret_1m > 0
        and t.RSI < 80
        and t.Close > t.SMA50
    )
    return hit, float(ret_3m * 100), "FIRED"


def s_squeeze(d: pd.DataFrame, include_setups: bool = False):
    t = d.iloc[-1]
    bw = d["BBWidth"]
    squeezed = bw.iloc[-6:-1].min() <= bw.iloc[-120:].quantile(0.15)
    fired = t.Close > t.BBUpper or (
        t.Close > d["High"].iloc[-11:-1].max() and t.VolRatio >= 1.3
    )
    in_trend = t.Close > t.SMA200
    if squeezed and in_trend and fired and t.VolRatio >= 1.2:
        return True, float(t.VolRatio), "FIRED"
    if include_setups and squeezed and in_trend and not fired:
        return True, float(-bw.iloc[-1] * 100), "SETUP"
    return False, 0.0, ""


STRATEGIES = {
    "breakout": s_breakout,
    "pullback": s_pullback,
    "momentum": s_momentum,
    "near52w": s_near52w,
    "squeeze": s_squeeze,
}


# --------------------------------------------------------------------------- #
# Scan
# --------------------------------------------------------------------------- #

def scan(frames: dict[str, pd.DataFrame], chosen: list[str],
         min_price: float, min_turnover_cr: float, include_setups: bool) -> pd.DataFrame:
    rows = []
    for sym, raw in frames.items():
        d = add_indicators(raw)
        t = d.iloc[-1]

        # Liquidity / sanity filters
        if (
            pd.isna(t.SMA200) or pd.isna(t.RSI) or pd.isna(t.VolRatio)
            or t.Close < min_price
            or t.Turnover20 < min_turnover_cr * 1e7
        ):
            continue

        hits, statuses = [], {}
        for name in chosen:
            fn = STRATEGIES[name]
            if name == "squeeze":
                ok, score, status = fn(d, include_setups)
            else:
                ok, score, status = fn(d)
            if ok:
                hits.append(name)
                statuses[name] = status
        if not hits:
            continue

        swing_low = float(d["Low"].iloc[-10:].min())
        atr_stop = float(t.Close - 2 * t.ATR)
        stop = max(swing_low, atr_stop)          # tighter of the two
        risk = float(t.Close) - stop
        risk_pct = risk / float(t.Close) * 100
        hi52 = float(d["High"].iloc[-252:].max())
        chg = (float(t.Close) / float(d["Close"].iloc[-2]) - 1) * 100

        is_setup_only = all(statuses.get(h) == "SETUP" for h in hits)
        rows.append({
            "Symbol": sym,
            "Strategies": "+".join(hits) + (" (SETUP)" if is_setup_only else ""),
            "NumHits": len(hits),
            "Close": round(float(t.Close), 1),
            "Chg%": round(chg, 1),
            "RSI": round(float(t.RSI), 0),
            "Volx": round(float(t.VolRatio), 1),
            "From52wH%": round((float(t.Close) / hi52 - 1) * 100, 1),
            "Trigger": round(float(t.High), 1),
            "Stop": round(stop, 1),
            "Target2R": round(float(t.Close) + 2 * risk, 1),
            "Risk%": round(risk_pct, 1),
            "Note": "risk wide - size down" if risk_pct > 8 else "",
        })

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["NumHits", "Volx"], ascending=False).drop(columns="NumHits")
    return out


# --------------------------------------------------------------------------- #
# Holdings - sell signals for open positions listed in holdings.csv
# --------------------------------------------------------------------------- #

def load_holdings() -> pd.DataFrame | None:
    path = BASE_DIR / "holdings.csv"
    if not path.exists():
        return None
    h = pd.read_csv(path)
    h.columns = [c.strip() for c in h.columns]
    missing = {"Symbol", "BuyDate", "BuyPrice"} - set(h.columns)
    if missing:
        print(f"! holdings.csv is missing columns: {missing} - skipping holdings check.")
        return None
    h["Symbol"] = h["Symbol"].astype(str).str.strip().str.upper()
    return h


def check_holdings(frames: dict[str, pd.DataFrame], holdings: pd.DataFrame) -> list[dict]:
    """Apply the 5 exit rules to each open position. Returns display rows."""
    rows = []
    for _, pos in holdings.iterrows():
        sym = pos["Symbol"]
        buy_price = float(pos["BuyPrice"])
        stop = float(pos["Stop"]) if pd.notna(pos.get("Stop")) else None
        try:
            buy_date = pd.to_datetime(pos["BuyDate"], format="mixed",
                                      dayfirst=True).date()
        except Exception:
            buy_date = None

        if sym not in frames:
            rows.append({"Symbol": sym, "Buy": buy_price, "Close": "-", "PnL%": "-",
                         "Days": "-", "EMA20": "-",
                         "Signal": "NO DATA - check the symbol spelling"})
            continue

        d = add_indicators(frames[sym])
        t = d.iloc[-1]
        close = float(t.Close)
        pnl = (close / buy_price - 1) * 100
        sessions = int((d.index.date > buy_date).sum()) if buy_date else 0

        if stop is not None and close < stop:
            signal = "SELL ALL - stop-loss hit"
        elif close < t.EMA20:
            signal = "SELL - closed below 20 EMA (trail exit)"
        elif sessions >= 10 and pnl < 3:
            signal = "SELL - time stop (10+ sessions, no progress)"
        elif stop is not None and close >= buy_price + 2 * (buy_price - stop):
            signal = "BOOK HALF - 2R target reached, trail rest with 20 EMA"
        elif t.RSI >= 80:
            signal = "HOLD - RSI 80+, tighten stop to yesterday's low"
        else:
            signal = "HOLD"

        rows.append({
            "Symbol": sym,
            "Buy": round(buy_price, 1),
            "Close": round(close, 1),
            "PnL%": round(pnl, 1),
            "Days": sessions,
            "EMA20": round(float(t.EMA20), 1),
            "Signal": signal,
        })
    return rows


# --------------------------------------------------------------------------- #
# Telegram phone alerts (optional - configure telegram.json)
# --------------------------------------------------------------------------- #

def send_telegram(text: str) -> bool:
    # Cloud/CI: credentials come from env vars (GitHub Actions secrets).
    # Local: fall back to telegram.json.
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        cfg_path = BASE_DIR / "telegram.json"
        if not cfg_path.exists():
            return False
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            token, chat_id = cfg["bot_token"], cfg["chat_id"]
        except Exception as exc:
            print(f"! telegram.json could not be read: {exc}")
            return False
        if "PASTE" in str(token):
            return False  # placeholder file not filled in yet
    try:
        for i in range(0, len(text), 3900):  # Telegram caps messages at 4096 chars
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text[i : i + 3900]},
                timeout=15,
            )
            if not resp.ok:
                print(f"! Telegram API error: {resp.text[:200]}")
                return False
    except Exception as exc:
        print(f"! Telegram send failed: {exc}")
        return False
    return True


def format_report(result: pd.DataFrame, holding_rows: list[dict] | None,
                  last_date, max_rows: int = 12) -> str:
    lines = [f"NSE Swing Scan - data {last_date:%d %b %Y}", ""]

    if result.empty:
        lines.append("No new setups today. Do not force a trade.")
    else:
        lines.append(f"Top setups {min(len(result), max_rows)} of {len(result)} "
                     "- buy only above Trigger, skip >3% gap-ups:")
        for i, r in enumerate(result.head(max_rows).to_dict("records"), 1):
            lines.append(f"{i}. {r['Symbol']}  [{r['Strategies']}]")
            lines.append(f"    Close {r['Close']} | Trig {r['Trigger']} | "
                         f"SL {r['Stop']} | Tgt {r['Target2R']}")

    lines.append("")
    if holding_rows is None:
        lines.append("Holdings: holdings.csv not set up yet.")
    elif not holding_rows:
        lines.append("Holdings: none listed.")
    else:
        lines.append("YOUR HOLDINGS:")
        for h in holding_rows:
            lines.append(f"- {h['Symbol']}: {h['Signal']}  (P&L {h['PnL%']}%)")

    lines += ["", "Rules: risk 1% per trade | no entry 1-2 days before results | "
              "longs only while NIFTY > 50 DMA."]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def previous_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:  # Sat/Sun
        d -= timedelta(days=1)
    return d


def latest_trading_data_date() -> date | None:
    """Quick single-ticker probe to see how fresh NSE data is."""
    try:
        probe = yf.download("RELIANCE.NS", period="7d", interval="1d",
                            progress=False, auto_adjust=True)
        if probe is None or probe.empty:
            return None
        return probe.index[-1].date()
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="NSE swing-trade screener (EOD).")
    ap.add_argument("--universe", choices=list(INDEX_URLS), default="nifty200")
    ap.add_argument("--strategy", nargs="+", choices=list(STRATEGIES),
                    default=list(STRATEGIES), help="default: all five")
    ap.add_argument("--setups", action="store_true",
                    help="also list squeeze SETUPs (watchlist, not yet broken out)")
    ap.add_argument("--min-price", type=float, default=50.0)
    ap.add_argument("--min-turnover", type=float, default=5.0,
                    help="min 20-day avg turnover in crore (default 5)")
    ap.add_argument("--no-csv", action="store_true", help="don't save results CSV")
    ap.add_argument("--notify", action="store_true",
                    help="send the report to Telegram (needs telegram.json)")
    ap.add_argument("--auto", action="store_true",
                    help="scheduled-run mode: skip if market was closed yesterday, "
                         "always notify")
    args = ap.parse_args()

    print(f"Run time : {datetime.now():%d-%b-%Y %H:%M}")

    if args.auto:
        fresh = latest_trading_data_date()
        if fresh is not None and fresh < previous_weekday(date.today()):
            print(f"Latest NSE data is {fresh:%d-%b-%Y}; yesterday was a market "
                  "holiday. Nothing new to scan - exiting.")
            return

    print(f"Universe : {args.universe}")
    print("Strategies:")
    for s in args.strategy:
        print(f"  - {s:9s} {STRATEGY_INFO[s]}")

    symbols = get_universe(args.universe)
    holdings = load_holdings()
    extra = ([s for s in holdings["Symbol"].tolist() if s not in symbols]
             if holdings is not None else [])
    if extra:
        print(f"Also fetching {len(extra)} held symbol(s) outside the universe: "
              f"{', '.join(extra)}")

    print(f"\nFetching daily history for {len(symbols) + len(extra)} symbols "
          f"(takes a few minutes)...")
    frames = fetch_history(symbols + extra)
    if not frames:
        sys.exit("No data downloaded - check your internet connection and retry.")

    last_date = max(df.index[-1] for df in frames.values())
    result = scan(frames, args.strategy, args.min_price, args.min_turnover, args.setups)

    print(f"\n=== Scan results | data as of {last_date:%d-%b-%Y} "
          f"| {len(result)} candidates ===\n")
    if result.empty:
        print("No stock passed the filters today. That is normal - "
              "good setups appear in clusters, not every day. Do NOT force a trade.")
    else:
        print(result.to_string(index=False))
        print(
            "\nHow to act on this (details in README.md):\n"
            "  1. Next session, buy ONLY if price crosses 'Trigger' (yesterday's high).\n"
            "  2. Skip the trade if it gaps up more than 3% above the Trigger.\n"
            "  3. Place stop-loss at 'Stop'. Book half at 'Target2R', trail the rest "
            "with the 20 EMA.\n"
            "  4. Risk max 1% of capital per trade: Qty = (capital x 1%) / "
            "(Entry - Stop).\n"
            "  5. Check the earnings date before entering - avoid fresh entries "
            "1-2 days before results."
        )

    holding_rows = check_holdings(frames, holdings) if holdings is not None else None
    if holding_rows is not None:
        print("\n=== Holdings - sell signals ===\n")
        if holding_rows:
            print(pd.DataFrame(holding_rows).to_string(index=False))
        else:
            print("holdings.csv has no positions listed.")
    else:
        print("\n(No holdings.csv found - copy holdings.sample.csv to holdings.csv "
              "to get sell signals for your positions.)")

    if not args.no_csv and not result.empty:
        RESULTS_DIR.mkdir(exist_ok=True)
        out = RESULTS_DIR / f"scan_{datetime.now():%Y-%m-%d_%H%M}.csv"
        result.to_csv(out, index=False)
        print(f"\nSaved: {out}")

    if args.notify or args.auto:
        sent = send_telegram(format_report(result, holding_rows, last_date))
        print("Telegram report: sent." if sent
              else "Telegram report: telegram.json not configured - see README "
                   "'Get it on your phone'.")


if __name__ == "__main__":
    main()
