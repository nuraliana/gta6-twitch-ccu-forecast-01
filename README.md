# gta6-twitch-ccu-forecast-01

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/nuraliana/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/nuraliana/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecasts how many people watch Grand Theft Auto VI live on Twitch in each hour of its release day (2026-11-19 UTC), from the first hour's print alone, as five quantiles an hour (5%, 25%, 50%, 75%, 95%). Scored by pinball loss on the log scale; the prize needs a lower loss than the best house entry.

## How it works

A big console launch's Twitch audience follows the shape of its rolling midnight unlock: hour 1 (00:00–01:00 UTC) already holds the regions that unlocked before UTC midnight, hours 2–4 sag into the night, the US East (~05:00Z) and US West (~08:00Z) unlocks lift the curve, and it peaks in the US daytime / European evening (hours 15–22) before easing off.

PC-simultaneous launches look nothing like that (hour 1 near zero, then a 100x surge at the global unlock), so the fit uses only the comparables that resemble GTA VI: console-only (no PC), not early-access contaminated, with a complete 24-hour release day. In the practice cases that is 7 launches (Ghost of Yōtei, Saros, Zelda: Tears of the Kingdom, Final Fantasy VII Rebirth, The Last of Us Part II, Ghost of Tsushima, Stellar Blade); in the final it is 11, because the four practice launches join the set.

For each hour h = 2..24 the model fits, over that subset, `log(v_h / v_1) ~ median_h + slope_h * (log(v_1) - ref)`. The size slope is real and concentrated in the daytime hours (about 0 at hours 2–7, about −0.3 at hours 15–22): a launch whose first hour is already huge grows less steeply to its peak. Medians, slopes and spreads are smoothed lightly across neighbouring hours, and the size adjustment is clamped to the subset's observed hour-1 range, so an unprecedented first hour cannot extrapolate the curve below its own level. Quantiles are log-normal around the fitted median with a per-hour spread from the residuals' interquartile range — the honest dispersion across past console launches, not a guessed width.

Validation is leave-one-out over the console-only comparables (the kit's scorer is server-only, so there is no local practice grade): mean pinball loss **0.196** vs the house persistence baseline's **0.344** on the same games, worst case 0.270 vs 0.601. A second regressor (viewers per channel) was tested and rejected — it is 0.90-correlated with hour-1 size and adds nothing. If the console subset is too small the fit falls back to all comparables; if nothing is usable it falls back to flat persistence, so every case always produces a valid forecast.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only, no network. Reads every `<id>.in` in the input directory and writes `<id>.out` (23 rows, hours 2–24) to the output directory. Deterministic; about 0.05 s per case, far inside the 8 s cap.

---

<sub>Entered on [make.fun](https://make.fun/?ref=ctnjhg8e&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
