"""Settle pending (active) trades by fetching NBA box scores from ESPN.

Runs in GitHub Actions daily. Reads dashboard/site/trades.json, finds trades with
status == "active" whose game_date has a final box score, computes outcome, and
rewrites trades.json with updated bankroll / pnl.

Uses ESPN's unauthenticated public scoreboard / summary endpoints because
stats.nba.com blocks cloud IP ranges used by GitHub Actions runners.

Idempotent: running twice won't double-settle — already-closed trades are left
alone. Safe to re-run on failure.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import unicodedata
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

SITE_DIR = pathlib.Path(__file__).resolve().parents[1] / "site"
TRADES_PATH = SITE_DIR / "trades.json"

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ESPN_SUMMARY    = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
USER_AGENT = "nba-predictor-dashboard/0.1 (+https://github.com/hugohamynen/nba-predictor-dashboard)"

STAT_TO_LABEL = {
    "points":   "PTS",
    "rebounds": "REB",
    "assists":  "AST",
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


def _http_get_json(url: str, params: dict | None = None, retries: int = 3, sleep_s: float = 2.0) -> dict:
    full = url if not params else f"{url}?{urlencode(params)}"
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(full, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            last_err = exc
            print(f"[warn] GET {full} failed (attempt {attempt}/{retries}): {exc}", file=sys.stderr)
            time.sleep(sleep_s * attempt)
    raise RuntimeError(f"failed to GET {full}: {last_err}")


def _final_events_on(date_iso: str) -> list[str]:
    """Return ESPN event IDs for games that are final on target_date (YYYY-MM-DD)."""
    yyyymmdd = date_iso.replace("-", "")
    data = _http_get_json(ESPN_SCOREBOARD, {"dates": yyyymmdd, "limit": 50})
    events = data.get("events", []) or []
    out: list[str] = []
    for ev in events:
        state = (((ev.get("status") or {}).get("type") or {}).get("state") or "").lower()
        if state == "post":
            out.append(str(ev.get("id")))
    return out


def _player_stats_for_events(event_ids: list[str]) -> dict[str, dict[str, float]]:
    """Normalized-player-name -> {PTS, REB, AST}."""
    out: dict[str, dict[str, float]] = {}
    for eid in event_ids:
        try:
            summary = _http_get_json(ESPN_SUMMARY, {"event": eid})
        except Exception as exc:
            print(f"[warn] summary fetch failed for event {eid}: {exc}", file=sys.stderr)
            continue
        boxscore = summary.get("boxscore") or {}
        for team_block in boxscore.get("players", []) or []:
            for stat_group in team_block.get("statistics", []) or []:
                labels: list[str] = stat_group.get("labels") or stat_group.get("names") or []
                idx_pts = labels.index("PTS") if "PTS" in labels else None
                idx_reb = labels.index("REB") if "REB" in labels else None
                idx_ast = labels.index("AST") if "AST" in labels else None
                for ath in stat_group.get("athletes", []) or []:
                    athlete = ath.get("athlete") or {}
                    name = athlete.get("displayName") or ""
                    key = _norm(name)
                    if not key:
                        continue
                    stats = ath.get("stats") or []
                    def _pick(i):
                        if i is None or i >= len(stats):
                            return 0.0
                        try:
                            return float(stats[i])
                        except (TypeError, ValueError):
                            return 0.0
                    out[key] = {
                        "PTS": _pick(idx_pts),
                        "REB": _pick(idx_reb),
                        "AST": _pick(idx_ast),
                    }
        time.sleep(0.4)
    return out


def _determine_hit(actual: float, line: float, side: str) -> bool:
    # Polymarket resolves ties (actual == line) as UNDER; mirror that.
    if side == "OVER":
        return actual > line
    return actual < line or actual == line


def _settle_trade(trade: dict, stats_by_player: dict[str, dict[str, float]]) -> bool:
    key = _norm(trade["player"])
    label = STAT_TO_LABEL.get(trade["stat"])
    if not label or key not in stats_by_player:
        return False
    actual = stats_by_player[key][label]
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
    current = round(starting + total_pnl, 2)
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
        event_ids = _final_events_on(d)
        print(f"  {d}: {len(event_ids)} final event(s)")
        if not event_ids:
            continue
        date_to_stats[d] = _player_stats_for_events(event_ids)

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
