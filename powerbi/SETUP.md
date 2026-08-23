# Power BI dashboard setup

The pipeline writes plain CSVs, so Power BI connects with zero custom code.

## 1. Connect the data

**Get Data → Web** and paste the *raw* GitHub URLs of your committed CSVs
(click a file in GitHub → **Raw** → copy the URL), e.g.:

```
https://raw.githubusercontent.com/<you>/fpl-analytics/main/data/players.csv
https://raw.githubusercontent.com/<you>/fpl-analytics/main/data/teams.csv
https://raw.githubusercontent.com/<you>/fpl-analytics/main/data/history.csv
https://raw.githubusercontent.com/<you>/fpl-analytics/main/data/predictions.csv
```

Using the web/raw URLs means each Power BI refresh automatically pulls whatever
the Tuesday job last committed — no re-importing.

## 2. Model relationships

In **Model view**, link:
- `players[team]` → `teams[id]`
- `history[element]` → `players[id]`
- `predictions[element]` → `players[id]`

Set these as single-direction, one-to-many (from the lookup side).

## 3. A few DAX measures worth adding

```DAX
Total Points        = SUM ( players[total_points] )
Avg Value (Pts/£m)  = AVERAGE ( players[value_ppm] )
Predicted Next GW   = SUM ( predictions[predicted_points] )
Model MAE           = MAX ( predictions[model_mae] )
```

## 4. Suggested pages

1. **Overview** — cards for total players, avg points, "last updated" (from
   `last_updated.txt` if you import it), and a bar chart of top-20 scorers.
2. **Value finder** — scatter of `price_m` (x) vs `total_points` (y), coloured
   by position; the top-left quadrant is cheap-and-productive. This is the page
   that photographs well for a portfolio.
3. **Form & fixtures** — line chart of points by gameweek (`history`) for
   selected players, with a position slicer.
4. **Projections** — table sorted by `predicted_points`, with `model_mae`
   shown prominently so the honesty of the model is visible, not hidden.

## 5. Scheduled refresh (the one honest caveat)

Automatic dashboard refresh in the Power BI *Service* requires **Power BI Pro**
(a paid licence). Without it:
- **Power BI Desktop** refreshes on demand — one click of **Refresh** pulls the
  latest committed CSVs. Free, but manual.
- The *data* is still fully automated (the Tuesday job), so "one click to
  refresh the view" is the only manual step.

If you have Pro (students often get it free via a university email — worth
checking), set a weekly scheduled refresh in the Service and the whole thing is
genuinely click-free end to end.
