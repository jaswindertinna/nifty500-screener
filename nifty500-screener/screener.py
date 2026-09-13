"""
Nifty 500 - "Retraced to 200 DMA after strong uptrend" screener.

Logic:
  1. At some point in the last LOOKBACK_DAYS trading days, the stock traded
     at least UPTREND_PCT (%) above its 200-day SMA.
  2. As of the latest close, the stock is within RETRACE_PCT (%) of its
     200-day SMA (either side).

Outputs a CSV to results/YYYY-MM-DD.csv and updates results/latest.csv.
Designed to run unattended (e.g. via GitHub Actions on a daily schedule).
"""

import io
import sys
import time
import datetime as dt
from pathlib import Path

import requests
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Config — tweak these as needed
# ---------------------------------------------------------------------------
UPTREND_PCT = 20.0        # stock must have been at least this % above 200DMA
LOOKBACK_DAYS = 125        # trading days to look back for that uptrend peak (~6 months)
RETRACE_BAND_PCT = 5.0     # now must be within this % of 200DMA (either side)
HISTORY_PERIOD = "18mo"    # how much daily history to pull (need 200DMA + lookback buffer)
BATCH_SIZE = 50            # tickers per yfinance batch download
BATCH_SLEEP_SEC = 3        # pause between batches to avoid rate limiting
RETRY_ATTEMPTS = 3

NIFTY500_CSV_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
FALLBACK_LIST_PATH = Path(__file__).parent / "nifty500_fallback.csv"

OUTPUT_DIR = Path(__file__).parent / "results"
OUTPUT_DIR.mkdir(exist_ok=True)

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,*/*",
}


def get_nifty500_symbols() -> list[str]:
    """Fetch the current Nifty 500 constituent list from NSE.
    Falls back to a locally cached CSV if the live fetch fails."""
    try:
        resp = requests.get(NIFTY500_CSV_URL, headers=NSE_HEADERS, timeout=20)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        symbols = df["Symbol"].astype(str).str.strip().tolist()
        if len(symbols) < 400:
            raise ValueError(f"Unexpectedly short list ({len(symbols)}) — treating as failure")
        # cache a fresh copy for future fallback use
        df.to_csv(FALLBACK_LIST_PATH, index=False)
        print(f"Fetched {len(symbols)} symbols live from NSE.")
        return symbols
    except Exception as e:
        print(f"WARNING: live NSE fetch failed ({e}). Trying fallback cache...")
        if FALLBACK_LIST_PATH.exists():
            df = pd.read_csv(FALLBACK_LIST_PATH)
            symbols = df["Symbol"].astype(str).str.strip().tolist()
            print(f"Using cached list of {len(symbols)} symbols (may be stale).")
            return symbols
        raise RuntimeError(
            "Could not fetch Nifty 500 list and no fallback cache exists. "
            "Run once with network access to seed nifty500_fallback.csv."
        )


def to_yf_ticker(symbol: str) -> str:
    """NSE symbols need a .NS suffix for yfinance. Handle a couple of
    known ticker-naming quirks between NSE's CSV and Yahoo Finance."""
    symbol = symbol.strip().upper()
    overrides = {
        "M&M": "M&M",  # yfinance handles the ampersand fine with .NS suffix
    }
    return f"{overrides.get(symbol, symbol)}.NS"


def download_batch(tickers: list[str]) -> pd.DataFrame:
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            data = yf.download(
                tickers,
                period=HISTORY_PERIOD,
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )
            return data
        except Exception as e:
            print(f"  Batch download attempt {attempt} failed: {e}")
            if attempt < RETRY_ATTEMPTS:
                time.sleep(5 * attempt)
    return pd.DataFrame()


def evaluate_stock(close: pd.Series) -> dict | None:
    """Apply the screen logic to one stock's close-price series."""
    close = close.dropna()
    if len(close) < 210:  # need enough history for a stable 200DMA + buffer
        return None

    sma200 = close.rolling(window=200).mean()
    pct_from_sma = (close - sma200) / sma200 * 100.0
    pct_from_sma = pct_from_sma.dropna()

    if pct_from_sma.empty:
        return None

    latest_pct = pct_from_sma.iloc[-1]
    latest_close = close.iloc[-1]
    latest_sma = sma200.iloc[-1]

    if abs(latest_pct) > RETRACE_BAND_PCT:
        return None

    lookback_window = pct_from_sma.iloc[-(LOOKBACK_DAYS + 1):-1] if len(pct_from_sma) > 1 else pct_from_sma
    if lookback_window.empty:
        return None

    peak_pct = lookback_window.max()
    peak_date = lookback_window.idxmax()

    if peak_pct < UPTREND_PCT:
        return None

    return {
        "peak_pct_above_200dma": round(float(peak_pct), 2),
        "peak_date": peak_date.strftime("%Y-%m-%d") if hasattr(peak_date, "strftime") else str(peak_date),
        "latest_close": round(float(latest_close), 2),
        "latest_200dma": round(float(latest_sma), 2),
        "current_pct_vs_200dma": round(float(latest_pct), 2),
    }


def render_html(df: pd.DataFrame, run_date: str, run_time: str, scanned: int, failed: int) -> str:
    """Render the day's results as a static, self-contained HTML page."""
    if df.empty:
        rows_html = (
            '<tr><td colspan="6" class="empty">No stocks matched today\'s criteria.</td></tr>'
        )
    else:
        row_parts = []
        for _, r in df.iterrows():
            pct = r["current_pct_vs_200dma"]
            side_class = "above" if pct >= 0 else "below"
            sign = "+" if pct >= 0 else ""
            row_parts.append(f"""
            <tr>
              <td class="sym">{r['symbol']}</td>
              <td class="num {side_class}">{sign}{pct:.2f}%</td>
              <td class="num">{r['latest_close']:.2f}</td>
              <td class="num">{r['latest_200dma']:.2f}</td>
              <td class="num">+{r['peak_pct_above_200dma']:.2f}%</td>
              <td class="num muted">{r['peak_date']}</td>
            </tr>""")
        rows_html = "".join(row_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nifty 500 — 200 DMA Retrace Screen</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0E1512;
    --panel: #131C17;
    --border: #263229;
    --text: #E6EFE9;
    --muted: #7E9689;
    --up: #5FAE82;
    --down: #C97B4A;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: 'IBM Plex Sans', sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  main {{
    max-width: 900px;
    margin: 0 auto;
    padding: 48px 24px 80px;
  }}
  h1 {{
    font-size: 22px;
    font-weight: 600;
    margin: 0 0 6px;
    letter-spacing: -0.01em;
  }}
  .criteria {{
    color: var(--muted);
    font-size: 14px;
    line-height: 1.6;
    margin: 0 0 28px;
    max-width: 62ch;
  }}
  .criteria code {{
    font-family: 'IBM Plex Mono', monospace;
    color: var(--text);
    background: var(--panel);
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 13px;
  }}
  .meta {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13px;
    color: var(--muted);
    padding: 14px 0;
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    margin-bottom: 24px;
  }}
  .meta span {{
    display: inline-block;
    margin-right: 24px;
  }}
  .meta strong {{ color: var(--text); font-weight: 500; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13.5px;
  }}
  thead th {{
    text-align: left;
    font-family: 'IBM Plex Sans', sans-serif;
    font-weight: 500;
    font-size: 12.5px;
    color: var(--muted);
    padding: 0 12px 10px;
    border-bottom: 1px solid var(--border);
  }}
  thead th.num, td.num {{ text-align: right; }}
  tbody td {{
    padding: 11px 12px;
    border-bottom: 1px solid var(--border);
    font-variant-numeric: tabular-nums;
  }}
  tbody tr:hover {{ background: var(--panel); }}
  td.sym {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-weight: 500;
    letter-spacing: 0.01em;
  }}
  td.above {{ color: var(--up); }}
  td.below {{ color: var(--down); }}
  td.muted {{ color: var(--muted); }}
  td.empty {{
    text-align: center;
    padding: 48px 12px;
    color: var(--muted);
    font-family: 'IBM Plex Sans', sans-serif;
  }}
  footer {{
    margin-top: 32px;
    color: var(--muted);
    font-size: 12.5px;
  }}
  @media (max-width: 640px) {{
    thead th:nth-child(5), td:nth-child(5),
    thead th:nth-child(6), td:nth-child(6) {{ display: none; }}
  }}
</style>
</head>
<body>
<main>
  <h1>Nifty 500 — 200 DMA Retrace</h1>
  <p class="criteria">
    Stocks that traded at least <code>20%</code> above their 200-day moving average
    within the last ~6 months, and have since retraced to within <code>5%</code>
    of the 200 DMA, either side.
  </p>
  <div class="meta">
    <span>Last run: <strong>{run_date} {run_time} IST</strong></span>
    <span>Scanned: <strong>{scanned}</strong></span>
    <span>Matches: <strong>{len(df)}</strong></span>
    <span>Failed to fetch: <strong>{failed}</strong></span>
  </div>
  <table>
    <thead>
      <tr>
        <th>Symbol</th>
        <th class="num">vs 200 DMA</th>
        <th class="num">Close</th>
        <th class="num">200 DMA</th>
        <th class="num">Peak above</th>
        <th class="num">Peak date</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
  <footer>Runs automatically on weekdays after market close. Data via Yahoo Finance, not investment advice.</footer>
</main>
</body>
</html>"""


def main():
    run_date = dt.date.today().isoformat()
    print(f"=== Nifty 500 200-DMA retrace screen — {run_date} ===")

    symbols = get_nifty500_symbols()
    yf_tickers = [to_yf_ticker(s) for s in symbols]

    matches = []
    errors = []

    for i in range(0, len(yf_tickers), BATCH_SIZE):
        batch = yf_tickers[i : i + BATCH_SIZE]
        print(f"Downloading batch {i // BATCH_SIZE + 1} "
              f"({i + 1}-{min(i + BATCH_SIZE, len(yf_tickers))} of {len(yf_tickers)})...")
        data = download_batch(batch)

        if data.empty:
            errors.extend(batch)
            continue

        for ticker in batch:
            try:
                if len(batch) == 1:
                    close = data["Close"]
                else:
                    if ticker not in data.columns.get_level_values(0):
                        errors.append(ticker)
                        continue
                    close = data[ticker]["Close"]
                result = evaluate_stock(close)
                if result:
                    result["symbol"] = ticker.replace(".NS", "")
                    matches.append(result)
            except Exception as e:
                errors.append(ticker)

        time.sleep(BATCH_SLEEP_SEC)

    if matches:
        out_df = pd.DataFrame(matches)[
            ["symbol", "current_pct_vs_200dma", "latest_close", "latest_200dma",
             "peak_pct_above_200dma", "peak_date"]
        ].sort_values("current_pct_vs_200dma", key=abs)
    else:
        out_df = pd.DataFrame(columns=[
            "symbol", "current_pct_vs_200dma", "latest_close", "latest_200dma",
            "peak_pct_above_200dma", "peak_date"
        ])

    dated_path = OUTPUT_DIR / f"{run_date}.csv"
    latest_path = OUTPUT_DIR / "latest.csv"
    out_df.to_csv(dated_path, index=False)
    out_df.to_csv(latest_path, index=False)

    run_time = dt.datetime.now().strftime("%H:%M")
    html = render_html(out_df, run_date, run_time, scanned=len(symbols), failed=len(errors))
    html_path = Path(__file__).parent / "index.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"Saved: {html_path}")

    print(f"\nMatches found: {len(out_df)}")
    print(f"Tickers that failed to download/process: {len(errors)}")
    if errors:
        print("  " + ", ".join(errors[:20]) + (" ..." if len(errors) > 20 else ""))
    print(f"\nSaved: {dated_path}")
    print(f"Saved: {latest_path}")

    if not out_df.empty:
        print("\n" + out_df.to_string(index=False))


if __name__ == "__main__":
    sys.exit(main())
