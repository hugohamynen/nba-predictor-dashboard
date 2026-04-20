"""Build site/trades.json from live paper-trading picks only.

Bankroll seeded at $1,000 on 2026-04-19 (the day paper-trading went live).
Historical model backtests are intentionally excluded — the honest verdict in
reports/SUMMARY.md is that they rode a late-regular-season OVER bias, not skill.

New live slates should be appended via scripts/append_picks.py (not implemented
yet) or by extending the LIVE_SLATES list below.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime

DASH_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_PATH = DASH_ROOT / "site" / "trades.json"

STARTING_BANKROLL = 1000.0
STAKE_PCT = 0.02  # 2% of starting bankroll per bet, flat


# One entry per live slate. edge = model P(win) - implied market P(win).
# Values come from reports/predictions_YYYY-MM-DD.xlsx (Recommended_Bets sheet).
LIVE_SLATES: list[dict] = [
    {
        "game_date": "2026-04-19",
        "bets": [
            {"player": "Jrue Holiday",   "stat": "rebounds", "line": 4.5,  "side": "UNDER",
             "price": 0.60, "p_model": 0.282051, "edge": 0.117949},
            {"player": "Jalen Duren",    "stat": "assists",  "line": 2.5,  "side": "OVER",
             "price": 0.50, "p_model": 0.611111, "edge": 0.111111},
            {"player": "Jalen Green",    "stat": "points",   "line": 18.5, "side": "OVER",
             "price": 0.55, "p_model": 0.642857, "edge": 0.092857},
            {"player": "Nikola Vucevic", "stat": "rebounds", "line": 6.5,  "side": "OVER",
             "price": 0.40, "p_model": 0.458523, "edge": 0.058523},
            {"player": "Devin Booker",   "stat": "points",   "line": 24.5, "side": "OVER",
             "price": 0.50, "p_model": 0.556818, "edge": 0.056818},
            {"player": "Neemias Queta",  "stat": "assists",  "line": 1.5,  "side": "OVER",
             "price": 0.56, "p_model": 0.611111, "edge": 0.051111},
        ],
    },
]


# Settlements: (game_date, player, stat) -> {actual, won}.
# Populated from NBA box scores. The settle_pending.py script overwrites
# trades.json with the authoritative result; entries here are seed data only
# so the chart isn't empty before the first CI run.
SEED_SETTLEMENTS: dict[tuple[str, str, str], dict] = {
    ("2026-04-19", "Jalen Duren",    "assists"):  {"actual": 1.0, "won": False},
    ("2026-04-19", "Jalen Green",    "points"):   {"actual": 17.0, "won": False},
    ("2026-04-19", "Nikola Vucevic", "rebounds"): {"actual": 6.0, "won": False},
    ("2026-04-19", "Devin Booker",   "points"):   {"actual": 23.0, "won": False},
    ("2026-04-19", "Neemias Queta",  "assists"):  {"actual": 1.0, "won": False},
}


def _flatten_slates() -> list[dict]:
    stake = round(STARTING_BANKROLL * STAKE_PCT, 2)
    rows: list[dict] = []
    for slate in LIVE_SLATES:
        for b in slate["bets"]:
            key = (slate["game_date"], b["player"], b["stat"])
            settled = SEED_SETTLEMENTS.get(key)
            entry = {
                "game_date": slate["game_date"],
                "player": b["player"],
                "stat": b["stat"],
                "line": b["line"],
                "side": b["side"],
                "price": b["price"],
                "stake": stake,
                "p_model": b.get("p_model"),
                "edge": b.get("edge"),
                "source": "live",
            }
            if settled:
                shares = stake / b["price"]
                pnl = (shares - stake) if settled["won"] else -stake
                entry.update({
                    "status": "closed",
                    "actual": settled["actual"],
                    "won": settled["won"],
                    "pnl": round(pnl, 2),
                })
            else:
                entry.update({
                    "status": "active",
                    "actual": None,
                    "won": None,
                    "pnl": None,
                })
            rows.append(entry)
    return rows


def _assign_bankroll(rows: list[dict]) -> list[dict]:
    # Sort chronologically (date → player → stat) so the chart + bankroll curve
    # follow insertion order. Closed bets accumulate; active bets get None.
    rows.sort(key=lambda r: (r["game_date"], r["player"], r["stat"]))
    bankroll = STARTING_BANKROLL
    for t in rows:
        if t["status"] == "closed":
            bankroll += float(t["pnl"])
            t["bankroll_after"] = round(bankroll, 2)
        else:
            t["bankroll_after"] = None
    return rows


def _summary(rows: list[dict]) -> dict:
    closed = [r for r in rows if r["status"] == "closed"]
    active = [r for r in rows if r["status"] == "active"]
    wins = [r for r in closed if r["won"]]
    total_pnl = round(sum(r["pnl"] for r in closed), 2)
    total_staked = round(sum(r["stake"] for r in closed), 2)
    current_bankroll = round(STARTING_BANKROLL + total_pnl, 2)
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
        "tracking_since": "2026-04-19",
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main() -> None:
    rows = _flatten_slates()
    _assign_bankroll(rows)
    payload = {"summary": _summary(rows), "trades": rows}
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    s = payload["summary"]
    print(f"wrote {OUT_PATH}")
    print(f"  tracking since: {s['tracking_since']}")
    print(f"  closed: {s['closed_count']}  wins: {s['wins']}  losses: {s['losses']}  active: {s['active_count']}")
    print(f"  ROI: {s['roi_pct']}%  pnl: ${s['total_pnl']}  bankroll: ${s['current_bankroll']}")


if __name__ == "__main__":
    main()
