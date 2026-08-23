"""
Build the value-finding table  (robust cross-season join on permanent id).

Headline signal of the project: last season's proven output vs THIS season's
price. A cheap player who scored heavily last year is underpriced; an
expensive one who didn't is a trap.

Matching a player across seasons is the tricky part. FPL reassigns the per-
season id ('element'/'id') every year, and names come in inconsistent short
forms, so neither is safe to join on. FPL also carries a PERMANENT player id
called 'code' that never changes - Salah is 118748 in every season. We join
on that, which removes all name guesswork.

Sources (community archive, same origin as seed_history):
    last season points:  <prev>/players_raw.csv  (code + total_points)
    this season price:   <now>/players_raw.csv   (code + now_cost)
    predictions:         data/predictions.csv     (from model.py)

Output: data/value_table.csv   (load THIS into Power BI)
"""

from __future__ import annotations

import io
import pathlib
import sys

import requests
import pandas as pd

SEASON_PREV = "2025-26"
SEASON_NOW = "2026-27"
REPO = ("https://raw.githubusercontent.com/vaastav/"
        "Fantasy-Premier-League/master/data")
HEADERS = {"User-Agent": "Mozilla/5.0 (fpl-analytics-project)"}
DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def fetch_csv(url: str) -> pd.DataFrame:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)

    print("Fetching last-season player totals...")
    prev = fetch_csv(f"{REPO}/{SEASON_PREV}/players_raw.csv")
    prev_pts = prev[["code", "total_points"]].rename(
        columns={"total_points": "points_last_season"})

    print("Fetching this-season roster + price...")
    now = fetch_csv(f"{REPO}/{SEASON_NOW}/players_raw.csv")
    now = now.assign(
        position=now["element_type"].map(POS),
        price_now=now["now_cost"] / 10.0,
    )
    table = now.merge(prev_pts, on="code", how="left")
    table["points_last_season"] = table["points_last_season"].fillna(0)

    pred_path = DATA_DIR / "predictions.csv"
    if pred_path.exists():
        preds = pd.read_csv(pred_path)[["element", "predicted_points"]]
        table = table.merge(preds.rename(columns={"element": "id"}),
                            on="id", how="left")
    else:
        table["predicted_points"] = pd.NA
        print("  note: no predictions.csv yet - column left blank",
              file=sys.stderr)

    table["value_last_per_m"] = (
        table["points_last_season"] /
        table["price_now"].replace(0, pd.NA)).round(2)

    out = (table[["code", "web_name", "position", "price_now",
                  "points_last_season", "predicted_points",
                  "value_last_per_m"]]
           .sort_values("points_last_season", ascending=False))
    out.to_csv(DATA_DIR / "value_table.csv", index=False)
    print(f"\nWrote value_table.csv ({len(out)} players)")
    print("\nTop 10 by last-season points (sanity check - stars should appear):")
    print(out.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
