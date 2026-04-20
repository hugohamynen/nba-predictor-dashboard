# NBA_MODEL // TERMINAL

Live paper-trading dashboard for an XGBoost NBA player-prop model on Polymarket.
Starting bankroll $1,000, flat 2% stake per bet, auto-settled nightly from NBA box scores.

**Live site:** https://hugohamynen.github.io/nba-predictor-dashboard/

## How it works

```
┌────────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  site/trades.json  │◄─────│  settle_pending  │◄─────│     nba_api      │
│  (source of truth) │      │  (runs nightly)  │      │   box scores     │
└─────────┬──────────┘      └──────────────────┘      └──────────────────┘
          │
          ▼
┌────────────────────┐
│   site/ (static)   │  ← served by GitHub Pages
│   index.html       │
│   style.css        │
│   app.js           │
└────────────────────┘
```

- `site/trades.json` is the single source of truth: every bet (historical + live) with status `closed` or `active`.
- `scripts/settle_pending.py` runs nightly in GitHub Actions, pulls final box scores for every active bet's `game_date` and flips them to `closed` with the right P&L.
- `site/` is a plain static page (HTML + CSS + Chart.js). No build step.

## Adding new picks (manual, v1)

The ML pipeline that *generates* picks lives in the sibling project and is too big
to run in free CI. For now, generate locally and paste-append:

```bash
cd ../nba_predictor              # parent project with the model
# generate tomorrow's picks (produces reports/predictions_YYYY-MM-DD.xlsx)
python scripts/generate_daily_predictions.py

# then append them to trades.json and push
cd ../dashboard
python scripts/append_picks.py ../nba_predictor/reports/predictions_YYYY-MM-DD.xlsx
git add site/trades.json
git commit -m "pick: YYYY-MM-DD slate"
git push
```

The settle workflow will pick them up the next morning after games.

## Local dev

```bash
cd site && python -m http.server 8000
# open http://localhost:8000
```

## Rebuild trades.json from scratch

```bash
python scripts/build_trades_json.py
```

Reads the backtest CSVs in `../nba_predictor/reports/` and the hard-coded live
bets (for audit), produces `site/trades.json`.

## Disclaimer

Research output. Not betting advice. The backtest shows the model does not beat
a naive "always-OVER during the last 2 weeks of regular season" baseline — see
`../nba_predictor/reports/SUMMARY.md` for the honest verdict.
