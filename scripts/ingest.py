"""
FPL data ingestion.

Pulls the official Fantasy Premier League API and writes three tidy CSVs
into ./data that Power BI and the R modelling layer both read.

No API key required. The endpoints are public. This script is defensive:
if the API shape shifts (FPL occasionally tweaks it in the off-season),
missing columns are filled rather than crashing the pipeline.

Outputs:
    data/players.csv   one row per player, current-season totals + form
    data/teams.csv     one row per club (lookup for names/strength)
    data/history.csv   one row per player per finished gameweek (the panel
                       used for modelling and for any time-series charts)
"""

from __future__ import annotations

import sys
import time
import pathlib
from datetime import datetime, timezone

import requests
import pandas as pd

BASE = "https://fantasy.premierleague.com/api"
# A browser-like UA avoids the occasional 403 from the FPL edge.
HEADERS = {"User-Agent": "Mozilla/5.0 (fpl-analytics-project)"}
DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

# Player fields we keep. Everything else in the API is dropped to keep the
# table readable. Add to this list if you want more signal in the model.
PLAYER_COLS = [
    "id", "web_name", "first_name", "second_name", "team",
    "element_type",           # position id: 1 GK, 2 DEF, 3 MID, 4 FWD
    "now_cost",               # price in tenths of a million (55 = £5.5m)
    "total_points", "event_points", "points_per_game", "form",
    "selected_by_percent", "minutes", "goals_scored", "assists",
    "clean_sheets", "goals_conceded", "yellow_cards", "red_cards",
    "bonus", "bps", "influence", "creativity", "threat", "ict_index",
    "expected_goals", "expected_assists", "expected_goal_involvements",
    "expected_goals_conceded", "starts",
    "transfers_in_event", "transfers_out_event", "status",
]

POSITION_MAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def get(url: str, retries: int = 3, pause: float = 2.0) -> dict:
    """GET with a couple of retries; FPL edge is occasionally flaky."""
    last = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - we genuinely want any failure
            last = exc
            print(f"  retry {attempt + 1}/{retries} on {url}: {exc}",
                  file=sys.stderr)
            time.sleep(pause)
    raise RuntimeError(f"Failed after {retries} tries: {url}") from last


def coerce_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """FPL returns several numeric fields as strings ('form', xG, etc)."""
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def build_players(bootstrap: dict) -> pd.DataFrame:
    df = pd.DataFrame(bootstrap["elements"])
    # Keep only the columns we care about, tolerating any that vanish.
    keep = [c for c in PLAYER_COLS if c in df.columns]
    missing = set(PLAYER_COLS) - set(keep)
    if missing:
        print(f"  note: API missing {sorted(missing)} - filled as NA",
              file=sys.stderr)
    df = df[keep].copy()
    for c in missing:
        df[c] = pd.NA

    numeric = [c for c in PLAYER_COLS if c not in
               ("web_name", "first_name", "second_name", "status")]
    df = coerce_numeric(df, numeric)

    df["position"] = df["element_type"].map(POSITION_MAP)
    df["price_m"] = df["now_cost"] / 10.0
    df["full_name"] = (df["first_name"].fillna("") + " " +
                       df["second_name"].fillna("")).str.strip()
    # Points per £m: a cheap, interview-friendly value metric.
    df["value_ppm"] = (df["total_points"] /
                       df["price_m"].replace(0, pd.NA)).round(2)
    return df


def build_teams(bootstrap: dict) -> pd.DataFrame:
    df = pd.DataFrame(bootstrap["teams"])
    keep = [c for c in ["id", "name", "short_name", "strength",
                        "strength_overall_home", "strength_overall_away",
                        "strength_attack_home", "strength_attack_away",
                        "strength_defence_home", "strength_defence_away"]
            if c in df.columns]
    return df[keep].copy()


def build_history(bootstrap: dict) -> pd.DataFrame:
    """
    Per-player per-gameweek panel. This is the expensive part: one API call
    per player (~700 calls). We only pull it for players who have logged any
    minutes, which trims dead weight (unregistered / never-selected players).
    """
    players = bootstrap["elements"]
    active = [p for p in players if (p.get("minutes") or 0) > 0]
    rows = []
    total = len(active)
    print(f"  pulling gameweek history for {total} active players...")
    for i, p in enumerate(active, 1):
        pid = p["id"]
        try:
            summary = get(f"{BASE}/element-summary/{pid}/")
        except RuntimeError as exc:
            print(f"  skip player {pid}: {exc}", file=sys.stderr)
            continue
        for gw in summary.get("history", []):
            rows.append(gw)
        if i % 100 == 0:
            print(f"    {i}/{total}")
        time.sleep(0.05)  # be polite to the API

    hist = pd.DataFrame(rows)
    if hist.empty:
        return hist
    # element -> player id; round -> gameweek number.
    numeric = [c for c in hist.columns
               if c not in ("kickoff_time",)]
    hist = coerce_numeric(hist, numeric)
    return hist


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{stamp}] FPL ingest starting")

    bootstrap = get(f"{BASE}/bootstrap-static/")
    print(f"  players={len(bootstrap['elements'])} "
          f"teams={len(bootstrap['teams'])} "
          f"events={len(bootstrap['events'])}")

    players = build_players(bootstrap)
    teams = build_teams(bootstrap)

    # Attach readable team name to the player table for Power BI convenience.
    players = players.merge(
        teams[["id", "name", "short_name"]].rename(
            columns={"id": "team", "name": "team_name"}),
        on="team", how="left")

    players.to_csv(DATA_DIR / "players.csv", index=False)
    teams.to_csv(DATA_DIR / "teams.csv", index=False)
    print(f"  wrote players.csv ({len(players)}) and teams.csv ({len(teams)})")

    history = build_history(bootstrap)
    if not history.empty:
        history.to_csv(DATA_DIR / "history.csv", index=False)
        print(f"  wrote history.csv ({len(history)} player-gameweeks)")
    else:
        print("  history empty (pre-season?) - skipped history.csv")

    # Small metadata file so the dashboard can show 'last updated'.
    (DATA_DIR / "last_updated.txt").write_text(stamp + "\n")
    print("[done]")


if __name__ == "__main__":
    main()
