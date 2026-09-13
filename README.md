# Nifty 500 — 200 DMA Retrace Screener

Finds Nifty 500 stocks that:
1. Were at least **20% above** their 200-day moving average at some point in the
   last ~125 trading days (roughly 6 months), and
2. Have since retraced to **within 5%** of the 200 DMA (above or below).

Runs fully automatically once a day via GitHub Actions — nothing to run on your
own machine.

## One-time setup (~5 minutes)

1. **Create a GitHub repo** (free account is fine) and upload these files,
   keeping the folder structure:
   ```
   screener.py
   requirements.txt
   .github/workflows/daily_screen.yml
   ```
   Easiest way: create a new repo on github.com, then drag-and-drop these
   files/folders in via "Add file → Upload files".

2. That's it. The workflow is already scheduled to run **every weekday at
   5:00 PM IST** (after market close), automatically, forever — no server,
   no laptop required. GitHub runs it on their infrastructure for free
   (public repos get unlimited free Action minutes; private repos get a
   generous free monthly quota, which this easily fits in).

3. Each day's results land in the repo as:
   - `index.html` — a styled webpage with the day's matches (updated every run)
   - `results/YYYY-MM-DD.csv` — that day's snapshot as CSV
   - `results/latest.csv` — always the most recent run as CSV

4. **Turn on GitHub Pages** so `index.html` is viewable as a real webpage:
   - In your repo, go to **Settings → Pages**
   - Under "Build and deployment" → Source, choose **Deploy from a branch**
   - Branch: **main**, folder: **/ (root)** → Save
   - GitHub gives you a URL like `https://yourusername.github.io/your-repo-name/`
     — bookmark it. It updates automatically every day after the workflow runs
     (usually live within a minute or two of the run finishing).

## Optional: get it emailed to you instead of checking GitHub

The workflow file has a commented-out "Email results" step at the bottom.
To enable it:
1. Uncomment that block in `.github/workflows/daily_screen.yml`
2. In your repo → Settings → Secrets and variables → Actions, add:
   - `MAIL_USERNAME` — your Gmail address
   - `MAIL_PASSWORD` — a Gmail "App Password" (not your normal password —
     generate one at myaccount.google.com/apppasswords)
3. Replace `your-email@example.com` with your real address.

## Adjusting the criteria

Open `screener.py` and change these constants near the top:

| Constant            | Meaning                                            | Default |
|---------------------|-----------------------------------------------------|---------|
| `UPTREND_PCT`        | Minimum % above 200DMA required at the prior peak  | 20      |
| `LOOKBACK_DAYS`       | How many trading days back to look for that peak    | 125 (~6mo) |
| `RETRACE_BAND_PCT`    | How close to the 200DMA it must be now (±%)         | 5       |

Commit the change and the next scheduled run will use the new values.

## Running it manually / testing locally

```bash
pip install -r requirements.txt
python screener.py
```

You can also trigger a run on-demand from GitHub: go to the **Actions** tab →
"Daily Nifty 500 200-DMA Screen" → **Run workflow**.

## Notes & limitations

- **Data source**: Yahoo Finance via `yfinance`. Free, no API key needed, but
  occasionally rate-limits large batch requests — the script batches tickers
  and retries automatically to handle this.
- **Nifty 500 list**: fetched live from NSE's official CSV on every run, so
  it stays current with index reconstitutions automatically. If NSE's site
  is briefly unreachable, it falls back to the last successfully cached list
  (`nifty500_fallback.csv`, auto-created after the first successful run).
- **Survivorship note**: this checks the *current* Nifty 500 membership each
  day — it doesn't try to reconstruct historical index membership.
