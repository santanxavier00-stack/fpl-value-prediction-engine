"""
Seed the pipeline with last season's completed data.

The live FPL API only holds the *current* season's per-gameweek detail, which
means before the season starts there's nothing for the model to learn from.
This script pulls last season's full per-gameweek panel from the community
archive (vaastav/Fantasy-Premier-League) and writes it in the same shape as
the history.csv that ingest.py produces, so the model can train immediately.

Run this ONCE before the season (or whenever you want the historical base).
During the season, ingest.py appends the current season on top.

Outputs:
    data/history.csv   last season's per-player per-gameweek panel

Also refreshes players.csv / teams.csv from the live API if they're missing,
so a first-time user gets a complete set from this one script.
"""

from __future__ import annotations

import io
import pathlib

import requests
import pandas as pd

SEASON = "2025-26"                       # last completed season
REPO = ("https://raw.githubusercontent.com/vaastav/"
        "Fantasy-Premier-League/master/data")
HEADERS = {"User-Agent": "Mozilla/5.0 (fpl-analytics-project)"}
DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

# Columns the model + dashboard use, in history.csv terms. Everything the
# archive provides beyond this is dropped to match ingest.py's output.
KEEP = [
    "element", "round", "total_points", "minutes", "was_home",
    "opponent_team", "expected_goals", "expected_assists",
    "expected_goal_involvements", "expected_goals_conceded",
    "ict_index", "influence", "creativity", "threat",
    "goals_scored", "assists", "clean_sheets", "bonus", "bps",
    "value", "transfers_balance", "selected",
]


def fetch_csv(url: str) -> pd.DataFrame:
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text))


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    print(f"Downloading {SEASON} gameweek panel...")

    gw = fetch_csv(f"{REPO}/{SEASON}/gws/merged_gw.csv")
    print(f"  got {len(gw):,} player-gameweek rows across "
          f"{gw['round'].nunique()} gameweeks")

    # was_home comes as True/False -> make it 0/1 like the live API path.
    if gw["was_home"].dtype == bool:
        gw["was_home"] = gw["was_home"].astype(int)

    keep = [c for c in KEEP if c in gw.columns]
    history = gw[keep].copy()

    history.to_csv(DATA_DIR / "history.csv", index=False)
    print(f"  wrote history.csv ({len(history):,} rows, {len(keep)} cols)")
    print("\nDone. You can now run: python scripts/model.py")
    print("The model will train on last season and, once this season's "
          "gameweeks arrive via ingest.py, use those too.")


if __name__ == "__main__":
    main()
