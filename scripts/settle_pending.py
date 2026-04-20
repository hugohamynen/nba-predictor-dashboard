"""Settle pending (active) trades by fetching NBA box scores.

Runs in GitHub Actions daily. Reads dashboard/site/trades.json, finds trades with
status == "active" whose game_date has a final box score, computes outcome, and
rewrites trades.json with updated bankroll / pnl.

Idempotent: running twice won't double-settle — already-closed trades are left
alone. Safe to re-run on failure.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import unicodedata
from datetime import datetime, timedelta

SITE_DIR = pathlib.Path(__file__).resolve().parents[1] / "site"
TRADES_PATH = SITE_DIR / "trades.json"

STAT_KEY = {
    "points": "points",
    "rebounds": "reboundsTotal",
    "assists": "assists",
}


def _norm(name: str) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def _load() -> dict:
    return json.loads(TRADES_PATH.read_text())


def _save(payload: dict) -> None:
    TRADES_PATH.write_text(json.dumps(payload, indent=2))


def _games_on_date(target_date: str) -> list[str]:
    from nba_api.stats.endpoints import scoreboardv2

    sb = scoreboardv2.ScoreboardV2(game_date=target_date)
    df = sb.game_header.get_data_frame()
    if df.empty:
        return []
    finals = df[df["GAME_STATUS_TEXT"].str.strip().str.lower() == "final"]
    return sorted(set(finals["GAME_ID"].astype(str).tolist()))


def _player_stats_for_games(game_ids: list[str]) -> dict[str, dict[str, float]]:
    """Return {normalized_player_name: {"points": x, "reboundsTotal": y, "assists": z}}."""
    from nba_api.stats.endpoints import boxscoretraditionalv3

    out: dict[str, dict[str, float]] = {}
    for gid in game_ids:
        try:
            bs = boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=gid)
            df = bs.player_stats.get_data_frame()
        except Exception as exc:
            print(f"[warn] box score fetch failed for {gid}: {exc}", file=sys.stderr)
            time.sleep(2)
            continue
        for _, r in df.iterrows():
            name = f"{r.get('firstName','')} {r.get('familyName','')}".strip()
            key = _norm(name)
            if not key:
                continue
            out[key] = {
                "points": float(r.get("points") or 0),
                "reboundsTotal": float(r.get("reboundsTotal") or 0),
                "assists": float(r.get("assists") or 0),
            }
        time.sleep(1)
    return out


def _determine_hit(actual: float, line: float, side: str) -> bool:
    # Polymarket resolves the tie (actual == line) as UNDER conventionally; we mirror that.
    if side == "OVER":
        return actual > line
    return actual < line or actual == line


def _settle_trade(trade: dict, stats_by_player: dict[str, dict[str, float]]) -> bool:
    key = _norm(trade["player"])
    stat_key = STAT_KEY.get(trade["stat"])
    if not stat_key or key not in stats_by_player:
        return False
    actual = stats_by_player[key][stat_key]
    won = _determine_hit(actual, float(trade["line"]), trade["side"])
    stake = float(trade["stake"])
    price = float(trade["price"])
    pnl = (stake / price - stake) if won else -stake
    trade["actual"] = actual
    trade["won"] = bool(won)
    trade["pnl"] = round(pnl, 2)
    trade["status"] = "closed"
    return True


def _recompute_bankroll(trades: list[dict], starting: float) -> None:
    bankroll = starting
    for t in trades:
        if t["status"] != "closed":
            t["bankroll_after"] = None
            continue
        bankroll += float(t["pnl"])
        t["bankroll_after"] = round(bankroll, 2)


def _recompute_summary(payload: dict) -> None:
    trades = payload["trades"]
    closed = [t for t in trades if t["status"] == "closed"]
    active = [t for t in trades if t["status"] == "active"]
    wins = [t for t in closed if t["won"]]
    total_pnl = round(sum(float(t["pnl"]) for t in closed), 2)
    total_staked = round(sum(float(t["stake"]) for t in closed), 2)
    starting = float(payload["summary"]["starting_bankroll"])
    current = closed[-1]["bankroll_after"] if closed else starting
    payload["summary"].update({
        "current_bankroll": current,
        "total_pnl": total_pnl,
        "total_staked": total_staked,
        "roi_pct": round(100.0 * total_pnl / total_staked, 2) if total_staked else 0.0,
        "closed_count": len(closed),
        "active_count": len(active),
        "wins": len(wins),
        "losses": len(closed) - len(wins),
        "win_rate_pct": round(100.0 * len(wins) / len(closed), 2) if closed else 0.0,
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


def main() -> int:
    payload = _load()
    trades = payload["trades"]
    active = [t for t in trades if t["status"] == "active"]
    if not active:
        print("no active trades to settle")
        _recompute_summary(payload)
        _save(payload)
        return 0

    dates = sorted({t["game_date"] for t in active})
    print(f"found {len(active)} active trade(s) across dates: {dates}")

    date_to_stats: dict[str, dict[str, dict[str, float]]] = {}
    for d in dates:
        game_ids = _games_on_date(d)
        print(f"  {d}: {len(game_ids)} final game(s)")
        if not game_ids:
            continue
        date_to_stats[d] = _player_stats_for_games(game_ids)

    settled = 0
    for t in active:
        stats = date_to_stats.get(t["game_date"], {})
        if _settle_trade(t, stats):
            settled += 1
            verdict = "WIN" if t["won"] else "LOSS"
            print(f"  settled: {t['game_date']} {t['player']} {t['stat']} {t['side']} {t['line']} → actual {t['actual']} [{verdict}]")

    print(f"settled {settled} of {len(active)} active trade(s)")

    _recompute_bankroll(trades, float(payload["summary"]["starting_bankroll"]))
    _recompute_summary(payload)
    _save(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
