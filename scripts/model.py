"""
FPL expected-points model (Python).

A direct mirror of scripts/model.R for people who'd rather keep the whole
pipeline in one language, and a tested fallback for the R version.

Reads  data/history.csv + data/players.csv
Writes data/predictions.csv

Same honest framing as the R script: predicts EXPECTED points for the next
gameweek and reports out-of-sample MAE from a time-based split, so the
accuracy figure you quote is defensible rather than in-sample.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"

FEATURES_NUM = [
    "form_pts_3", "form_mins_3", "form_xg_3", "form_xa_3", "form_ict_3",
    "cum_minutes", "was_home", "opp_pts_allowed", "price_m",
]


def rolling_mean(s: pd.Series, w: int = 3) -> pd.Series:
    return s.rolling(w, min_periods=1).mean()


def build_panel(history: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    h = history.sort_values(["element", "round"]).copy()

    # Tolerate missing optional columns from the API.
    for col, default in [("expected_goals", 0.0), ("expected_assists", 0.0),
                         ("ict_index", 0.0), ("minutes", 0),
                         ("was_home", 0), ("opponent_team", -1)]:
        if col not in h.columns:
            h[col] = default
        h[col] = pd.to_numeric(h[col], errors="coerce").fillna(default)

    g = h.groupby("element", group_keys=False)
    h["target_points"] = g["total_points"].shift(-1)          # next GW
    h["form_pts_3"] = g["total_points"].apply(rolling_mean)
    h["form_mins_3"] = g["minutes"].apply(rolling_mean)
    h["form_xg_3"] = g["expected_goals"].apply(rolling_mean)
    h["form_xa_3"] = g["expected_assists"].apply(rolling_mean)
    h["form_ict_3"] = g["ict_index"].apply(rolling_mean)
    h["cum_minutes"] = g["minutes"].cumsum()

    opp = (h.groupby("opponent_team")["total_points"]
             .mean().rename("opp_pts_allowed").reset_index())
    h = h.merge(opp, on="opponent_team", how="left")

    h = h.merge(players[["id", "position", "price_m"]]
                .rename(columns={"id": "element"}),
                on="element", how="left")
    return h


def add_position_dummies(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    pos = pd.Categorical(df["position"],
                         categories=["GK", "DEF", "MID", "FWD"])
    dummies = pd.get_dummies(pos, prefix="pos")
    df = pd.concat([df.reset_index(drop=True),
                    dummies.reset_index(drop=True)], axis=1)
    return df, list(dummies.columns)


def main() -> None:
    hist_path = DATA_DIR / "history.csv"
    players_path = DATA_DIR / "players.csv"

    if not hist_path.exists():
        print("No history.csv yet (pre-season / GW1 not finished). "
              "Nothing to model - exiting cleanly.")
        return

    history = pd.read_csv(hist_path)
    players = pd.read_csv(players_path)

    panel = build_panel(history, players)
    n_gw = panel["round"].nunique()

    model_df = panel.dropna(subset=["target_points", "form_pts_3",
                                    "position"]).copy()
    model_df, pos_cols = add_position_dummies(model_df)
    feature_cols = FEATURES_NUM + pos_cols

    # Fallback to naive baseline when data is too thin to trust a model.
    if len(model_df) < 200 or n_gw < 4:
        print(f"Only {n_gw} gameweeks / {len(model_df)} rows - using naive "
              "last-3 baseline instead of a fitted model.", file=sys.stderr)
        latest = (panel.sort_values("round").groupby("element").tail(1))
        out = latest[["element"]].copy()
        out["predicted_points"] = latest["form_pts_3"].fillna(0).round(2).values
        out["method"] = "baseline_last3_avg"
        out["model_mae"] = np.nan
    else:
        cutoff = model_df["round"].quantile(0.8)
        train = model_df[model_df["round"] <= cutoff]
        test = model_df[model_df["round"] > cutoff]

        model = HistGradientBoostingRegressor(
            max_iter=400, max_depth=4, learning_rate=0.05,
            min_samples_leaf=10, random_state=42)
        model.fit(train[feature_cols], train["target_points"])

        mae = mean_absolute_error(
            test["target_points"], model.predict(test[feature_cols]))
        print(f"Out-of-sample MAE: {mae:.2f} points")

        # Refit on everything, then predict each player's latest row.
        model.fit(model_df[feature_cols], model_df["target_points"])
        latest = (model_df.sort_values("round")
                  .groupby("element").tail(1))
        out = latest[["element"]].copy()
        out["predicted_points"] = model.predict(
            latest[feature_cols]).round(2)
        out["method"] = "hist_gradient_boosting"
        out["model_mae"] = round(mae, 2)

    out = (out.merge(players[["id", "web_name", "team_name", "position",
                              "price_m", "total_points", "form"]]
                     .rename(columns={"id": "element"}),
                     on="element", how="left")
              .sort_values("predicted_points", ascending=False))
    out.to_csv(DATA_DIR / "predictions.csv", index=False)
    print(f"Wrote predictions.csv ({len(out)} players)")


if __name__ == "__main__":
    main()
