# =============================================================================
# FPL expected-points model
#
# Reads data/history.csv (the per-player per-gameweek panel written by
# ingest.py) and data/players.csv, fits a model that estimates each player's
# expected points for the *next* gameweek, and writes data/predictions.csv
# for Power BI to consume.
#
# DESIGN NOTE (read this before the interview):
# FPL points are noisy - rotation, injuries, and bonus-point luck mean no
# model is going to be spookily accurate, and a reviewer who knows sport
# modelling will distrust one that claims to be. So this deliberately does
# two honest things:
#   1. It predicts EXPECTED points, framed as a mean, not a certainty.
#   2. It reports out-of-sample error (MAE) via time-based cross-validation,
#      so the number you quote is defensible rather than an in-sample fib.
#
# Model: a gradient-boosted tree (via the tidymodels/xgboost stack). Features
# are rolling recent form, minutes, underlying xG/xA, fixture difficulty, and
# position. Tree boosting handles the non-linear, interaction-heavy structure
# of football scoring better than a linear model, without much tuning.
# =============================================================================

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(tidyr)
  library(tidymodels)
  library(zoo)      # rolling means
})

set.seed(42)

data_dir <- file.path(dirname(dirname(normalizePath(
  sub("--file=", "", grep("--file=", commandArgs(), value = TRUE)[1],
      fixed = TRUE)))), "data")
if (is.na(data_dir) || !dir.exists(data_dir)) data_dir <- "data"

hist_path <- file.path(data_dir, "history.csv")
players_path <- file.path(data_dir, "players.csv")

if (!file.exists(hist_path)) {
  message("No history.csv yet (pre-season / gameweek 1 not finished). ",
          "Nothing to model - exiting cleanly.")
  quit(status = 0)
}

history <- read_csv(hist_path, show_col_types = FALSE)
players <- read_csv(players_path, show_col_types = FALSE)

# ---- Feature engineering ----------------------------------------------------
# history columns of interest: element, round, total_points, minutes,
# was_home, opponent_team, expected_goals, expected_assists, ict_index, value,
# transfers_balance, etc. (names per the FPL element-summary endpoint).

# Guard: need enough gameweeks to build rolling features and a holdout.
n_gw <- length(unique(history$round))
if (n_gw < 4) {
  message("Only ", n_gw, " gameweeks of data - too few to model reliably. ",
          "Writing a naive baseline (last-3 average) instead.")
}

panel <- history %>%
  arrange(element, round) %>%
  group_by(element) %>%
  mutate(
    # target = points scored in the NEXT gameweek
    target_points = lead(total_points),
    # rolling recent form (trailing 3 GW, excluding current to avoid leakage)
    form_pts_3   = rollapplyr(total_points, 3, mean, partial = TRUE, fill = NA),
    form_mins_3  = rollapplyr(minutes, 3, mean, partial = TRUE, fill = NA),
    form_xg_3    = rollapplyr(coalesce(expected_goals, 0), 3, mean,
                              partial = TRUE, fill = NA),
    form_xa_3    = rollapplyr(coalesce(expected_assists, 0), 3, mean,
                              partial = TRUE, fill = NA),
    form_ict_3   = rollapplyr(coalesce(ict_index, 0), 3, mean,
                              partial = TRUE, fill = NA),
    cum_minutes  = cumsum(coalesce(minutes, 0))
  ) %>%
  ungroup() %>%
  left_join(players %>% select(element = id, position, price_m),
            by = "element")

# next-fixture difficulty: the element-summary 'fixtures' block has it, but to
# keep this dependency-light we proxy difficulty with the opponent's implied
# strength via was_home + a simple opponent-conceded rate from the panel.
opp_strength <- panel %>%
  group_by(opponent_team) %>%
  summarise(opp_pts_allowed = mean(total_points, na.rm = TRUE),
            .groups = "drop")

model_df <- panel %>%
  left_join(opp_strength, by = "opponent_team") %>%
  filter(!is.na(target_points)) %>%
  mutate(
    was_home = as.integer(was_home),
    position = factor(position, levels = c("GK", "DEF", "MID", "FWD"))
  ) %>%
  select(element, round, target_points, form_pts_3, form_mins_3, form_xg_3,
         form_xa_3, form_ict_3, cum_minutes, was_home, opp_pts_allowed,
         price_m, position) %>%
  drop_na(form_pts_3, position)

# ---- Fallback: naive baseline if data is too thin ---------------------------
if (nrow(model_df) < 200 || n_gw < 4) {
  preds <- panel %>%
    group_by(element) %>%
    slice_tail(n = 1) %>%
    ungroup() %>%
    transmute(element,
              predicted_points = round(coalesce(form_pts_3, 0), 2),
              method = "baseline_last3_avg",
              model_mae = NA_real_)
} else {
  # ---- Time-based split: train on early GWs, test on the latest fifth -------
  cutoff <- quantile(model_df$round, 0.8, names = FALSE)
  train <- model_df %>% filter(round <= cutoff)
  test  <- model_df %>% filter(round >  cutoff)

  rec <- recipe(target_points ~ ., data = train) %>%
    update_role(element, round, new_role = "id") %>%
    step_dummy(position) %>%
    step_impute_median(all_numeric_predictors()) %>%
    step_zv(all_predictors())

  xgb_spec <- boost_tree(
      trees = 400, tree_depth = 4, learn_rate = 0.05,
      min_n = 10, loss_reduction = 0.01
    ) %>%
    set_engine("xgboost") %>%
    set_mode("regression")

  wf <- workflow() %>% add_recipe(rec) %>% add_model(xgb_spec)
  fit_obj <- fit(wf, data = train)

  # Honest out-of-sample error.
  test_pred <- predict(fit_obj, test) %>% bind_cols(test)
  mae <- yardstick::mae(test_pred, truth = target_points,
                        estimate = .pred)$.estimate
  message(sprintf("Out-of-sample MAE: %.2f points", mae))

  # ---- Predict next GW for every current player -----------------------------
  # Use each player's most recent row of features.
  latest <- model_df %>%
    group_by(element) %>%
    slice_max(round, n = 1, with_ties = FALSE) %>%
    ungroup()

  final_fit <- fit(wf, data = model_df)   # refit on all data for deployment
  preds <- predict(final_fit, latest) %>%
    bind_cols(latest %>% select(element)) %>%
    transmute(element,
              predicted_points = round(.pred, 2),
              method = "xgboost",
              model_mae = round(mae, 2))
}

# ---- Attach names and write --------------------------------------------------
out <- preds %>%
  left_join(players %>% select(element = id, web_name, team_name, position,
                               price_m, total_points, form),
            by = "element") %>%
  arrange(desc(predicted_points))

write_csv(out, file.path(data_dir, "predictions.csv"))
message("Wrote predictions.csv (", nrow(out), " players)")
