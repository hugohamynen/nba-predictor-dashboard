"""Consolidate historical backtest + live paper-trading bets into trades.json.

Output schema: see README. Bankroll starts at $1000, each bet stakes 2% flat.
Historical bets from three model backtests are replayed in chronological order
with the same sizing rule so the curve is a single, honest paper-trading series.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime

import pandas as pd

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DASH_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_PATH = DASH_ROOT / "site" / "trades.json"

STARTING_BANKROLL = 1000.0
STAKE_PCT = 0.02  # 2% of starting bankroll per bet, flat


def load_backtest_bets() -> pd.DataFrame:
    frames = []
    for stat in ("assists", "points", "rebounds"):
        df = pd.read_csv(REPO_ROOT / "reports" / f"backtest_{stat}_v1.bets.csv")
        df = df[df["bet_side"].isin(["OVER", "UNDER"])].copy()
        df["stat_type"] = stat
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def replay_with_unified_bankroll(bets_df: pd.DataFrame) -> list[dict]:
    bets_df = bets_df.sort_values(["game_date", "player_name_nba", "stat_type"]).reset_index(drop=True)
    stake = STARTING_BANKROLL * STAKE_PCT
    bankroll = STARTING_BANKROLL
    rows = []
    for _, r in bets_df.iterrows():
        price = float(r["bet_price"])
        shares = stake / price
        if bool(r["bet_won"]):
            pnl = shares - stake
        else:
            pnl = -stake
        bankroll += pnl
        rows.append({
            "game_date": str(r["game_date"]),
            "player": str(r["player_name_nba"]),
            "stat": str(r["stat_type"]),
            "line": float(r["line"]),
            "side": str(r["bet_side"]),
            "price": price,
            "stake": round(stake, 2),
            "actual": float(r["actual_value"]),
            "status": "closed",
            "won": bool(r["bet_won"]),
            "pnl": round(pnl, 2),
            "bankroll_after": round(bankroll, 2),
            "source": "backtest",
        })
    return rows


def live_bets_2026_04_19() -> list[dict]:
    """The 6 bets from reports/predictions_2026-04-19.xlsx (generated 2026-04-18)."""
    return [
        {"game_date": "2026-04-19", "player": "Jrue Holiday",   "stat": "rebounds", "line": 4.5,  "side": "UNDER", "price": 0.60},
        {"game_date": "2026-04-19", "player": "Jalen Duren",    "stat": "assists",  "line": 2.5,  "side": "OVER",  "price": 0.50},
        {"game_date": "2026-04-19", "player": "Jalen Green",    "stat": "points",   "line": 18.5, "side": "OVER",  "price": 0.55},
        {"game_date": "2026-04-19", "player": "Nikola Vucevic", "stat": "rebounds", "line": 6.5,  "side": "OVER",  "price": 0.40},
        {"game_date": "2026-04-19", "player": "Devin Booker",   "stat": "points",   "line": 24.5, "side": "OVER",  "price": 0.50},
        {"game_date": "2026-04-19", "player": "Neemias Queta",  "stat": "assists",  "line": 1.5,  "side": "OVER",  "price": 0.56},
    ]


SETTLEMENTS_2026_04_19 = {
    ("Jalen Duren",    "assists"):  {"actual": 1.0, "won": False},
    ("Jalen Green",    "points"):   {"actual": 17.0, "won": False},
    ("Nikola Vucevic", "rebounds"): {"actual": 6.0, "won": False},
    ("Devin Booker",   "points"):   {"actual": 23.0, "won": False},
    ("Neemias Queta",  "assists"):  {"actual": 1.0, "won": False},
}


def attach_live_bets(historical_rows: list[dict]) -> list[dict]:
    bankroll = historical_rows[-1]["bankroll_after"] if historical_rows else STARTING_BANKROLL
    stake = STARTING_BANKROLL * STAKE_PCT
    out = list(historical_rows)
    for b in live_bets_2026_04_19():
        key = (b["player"], b["stat"])
        settled = SETTLEMENTS_2026_04_19.get(key)
        entry = {
            **b,
            "stake": round(stake, 2),
            "source": "live",
            "status": "closed" if settled else "active",
        }
        if settled:
            shares = stake / b["price"]
            pnl = (shares - stake) if settled["won"] else -stake
            bankroll += pnl
            entry["actual"] = settled["actual"]
            entry["won"] = settled["won"]
            entry["pnl"] = round(pnl, 2)
            entry["bankroll_after"] = round(bankroll, 2)
        else:
            entry["actual"] = None
            entry["won"] = None
            entry["pnl"] = None
            entry["bankroll_after"] = None
        out.append(entry)
    return out


def summary(rows: list[dict]) -> dict:
    closed = [r for r in rows if r["status"] == "closed"]
    active = [r for r in rows if r["status"] == "active"]
    wins = [r for r in closed if r["won"]]
    total_pnl = round(sum(r["pnl"] for r in closed), 2)
    total_staked = round(sum(r["stake"] for r in closed), 2)
    current_bankroll = closed[-1]["bankroll_after"] if closed else STARTING_BANKROLL
    return {
        "starting_bankroll": STARTING_BANKROLL,
        "current_bankroll": current_bankroll,
        "total_pnl": total_pnl,
        "total_staked": total_staked,
        "roi_pct": round(100.0 * total_pnl / total_staked, 2) if total_staked else 0.0,
        "closed_count": len(closed),
        "active_count": len(active),
        "wins": len(wins),
        "losses": len(closed) - len(wins),
        "win_rate_pct": round(100.0 * len(wins) / len(closed), 2) if closed else 0.0,
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main() -> None:
    hist_bets = load_backtest_bets()
    hist_rows = replay_with_unified_bankroll(hist_bets)
    all_rows = attach_live_bets(hist_rows)
    payload = {
        "summary": summary(all_rows),
        "trades": all_rows,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    s = payload["summary"]
    print(f"wrote {OUT_PATH}")
    print(f"  closed: {s['closed_count']}  wins: {s['wins']}  losses: {s['losses']}  win%: {s['win_rate_pct']}")
    print(f"  ROI: {s['roi_pct']}%  pnl: ${s['total_pnl']}  bankroll: ${s['current_bankroll']}  active: {s['active_count']}")


if __name__ == "__main__":
    main()
