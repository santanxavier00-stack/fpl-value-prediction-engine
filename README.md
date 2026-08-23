# FPL Analytics Pipeline

An automated data pipeline for Fantasy Premier League: it pulls live data from
the official FPL API every gameweek, engineers features, fits an
expected-points model, and feeds a Power BI dashboard of top performers, value
picks, and next-gameweek projections.

**Stack:** Python (ingestion + automation) · R *or* Python (modelling) ·
GitHub Actions (scheduling) · Power BI (visualisation)

---

## What it does

1. **Ingest** (`scripts/ingest.py`) — calls the public FPL API
   (`bootstrap-static` + per-player `element-summary`), no API key required,
   and writes three tidy tables:
   - `data/players.csv` — one row per player: price, points, form, ownership,
     underlying xG/xA, and a `value_ppm` (points per £m) metric.
   - `data/teams.csv` — club lookup with FPL strength ratings.
   - `data/history.csv` — one row per player per finished gameweek (the panel
     the model trains on).
2. **Model** (`scripts/model.py` or `scripts/model.R`) — engineers rolling
   form/minutes/xG features, fits a gradient-boosted tree, and writes
   `data/predictions.csv` with each player's expected points for the next
   gameweek and the model's out-of-sample error.
3. **Automate** (`.github/workflows/weekly-refresh.yml`) — runs the whole thing
   every Tuesday on GitHub Actions and commits the refreshed CSVs back to the
   repo. Zero clicks.
4. **Visualise** — Power BI reads the CSVs from the repo (see
   `powerbi/SETUP.md`).

## Why the model is framed the way it is

FPL scoring is genuinely noisy — rotation, injuries, and bonus-point luck put a
hard ceiling on predictability. This project therefore predicts **expected**
points (a mean, not a certainty) and reports **out-of-sample MAE** from a
time-based train/test split, so the accuracy figure is honest rather than an
in-sample overstatement. That framing is the point: it shows an understanding
of the problem, not just the ability to call `.fit()`.

## Run it locally

```bash
pip install -r requirements.txt
python scripts/ingest.py      # writes data/*.csv
python scripts/model.py       # writes data/predictions.csv
# or, for the R modelling layer:
# Rscript scripts/model.R
```

The first `ingest.py` run takes a few minutes (one API call per active
player). After GW1 finishes, `history.csv` and `predictions.csv` populate;
before then the model exits cleanly with a note.

## Two modelling languages?

By design. Python is smoother for API work and scheduling; R (`tidymodels`) is
a natural fit for the statistical layer. Both model scripts are equivalent —
pick one in the workflow file. The Python model is tested end-to-end; the R
model follows standard `tidymodels` patterns and may need a small column-name
tweak on first run once you've seen the real API field names.

## Repo layout

```
scripts/       ingest.py, model.py, model.R
data/          generated CSVs (committed by the weekly job)
.github/       weekly-refresh.yml (scheduled automation)
powerbi/       dashboard setup guide
```

## Data source

Official FPL API — `https://fantasy.premierleague.com/api/`. Public, free,
updates live each gameweek. Historical seasons (for deeper model training) are
available at the community repo `vaastav/Fantasy-Premier-League`.
