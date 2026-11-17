# gta6-twitch-ccu-forecast-01

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/nuraliana/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/nuraliana/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecasts Grand Theft Auto VI's launch-day Twitch concurrent viewers, hours 2–24 (UTC), as five quantiles per hour. Python 3.13, standard library only, no network, deterministic.

Built for [make.fun's Forecast GTA VI's launch-day Twitch viewers hour by hour bounty](https://make.fun/bounty/gta6-twitch-ccu-forecast-01) ($250 in USDC).

## Run

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=<kit>/input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

## Model — round 2 (median-of-three-estimators)

Each past launch is summarised as a log-ratio curve: `ln(viewers at hour h / viewers at hour 1)`, hour by hour. The forecast is fitted on **console-only** past launches (no PC, no early access — Death Stranding 2 is excluded because it had early access).

**Centre, per hour: the median of three estimators** — OLS slope of log-ratio on `ln(hour-1 print)`, Theil-Sen, and LAD — each smoothed across neighbouring hours and clamped to ±1.5 log units from the mean as an extrapolation guardrail. With only 6–11 training games, the median of three is more robust than OLS alone against one deviating launch: in leave-one-out validation 5 of 7 console games improved versus OLS alone (Saros −0.0111, Zelda −0.0127, FFVII −0.0056).

**Spread, per hour:** sigma = max(0.30, 1.1 × IQR(OLS residuals) / 1.349), with normal quantiles. The 0.30 floor dominates: a game's whole curve can shift as one block across the day by 0.25–0.35 log units, and that shift cannot be predicted from launch size alone — no tested second feature (channels, pre-launch signals, sequel status, weekday, Metacritic) explains it.

**Parameters are taken from the middle of a plateau, not a peak:** spread multiplier 1.0–1.2 all give LOO-7 0.1479–0.1484.

## Local validation

Leave-one-out over the 7 console launches (production protocol, training excludes early access):

| | LOO-7 | Practice mean |
|---|---|---|
| Starter (kit) | 0.3435 | — |
| Rebuild round 1 (OLS slope) | 0.1528 | 0.1920 |
| **This entry (round 2)** | **0.1480** | **0.1892** |

Typical miss ~27%. LOO over all 37 launches under the production-faithful protocol is 0.6752 versus 0.6719 for round 1 — practically tied; the round-2 gain is in the console population that matches the final (one real console launch day, 19 Nov 2026). The final trains on 11 games (7 console + 4 practice launches), so final performance should be slightly better than LOO-7.
