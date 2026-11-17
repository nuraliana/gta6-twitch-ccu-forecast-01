"""Forecast GTA VI's launch-day Twitch viewers, hour by hour, from its first hour.

Model (built from the case's own comparables, no network, stdlib only):

  A big console launch's Twitch audience follows a shape set by the rolling
  midnight unlock: hour 1 (00:00-01:00 UTC) already holds the regions that
  unlocked before UTC midnight (New Zealand, Australia, Asia, central Europe,
  the UK just unlocking), hours 2-4 sag into the night, the US East unlock
  (~05:00Z) and US West unlock (~08:00Z) lift the curve, and it peaks in the
  US daytime / European evening (hours 15-22) before easing off.

  PC-simultaneous launches look nothing like that (hour 1 near zero, then a
  100x surge at the global unlock), so the fit uses only the comparables that
  resemble GTA VI: console-only (no PC in `platforms`), not flagged
  early-access-contaminated, with a complete 24-hour release day and a
  positive hour-1 count. In the practice cases that is 7 launches; in the
  final it is 11, because the four practice launches join the set.

  For each hour h = 2..24 the model fits, over that subset,
      log(v_h / v_1)  ~  median_h + slope_h * (log(v_1) - ref)
  where ref is the subset's median log hour-1 count. The slope is real and
  concentrated in the daytime hours (about 0 at hours 2-7, about -0.3 at
  hours 15-22): a launch whose first hour is already huge grows less steeply
  to its peak. Medians, slopes and spreads are smoothed lightly across
  neighbouring hours (the true curve is smooth) and the size adjustment is
  clamped to the subset's observed hour-1 range, so an unprecedented GTA VI
  first hour cannot extrapolate the curve below its own level.

  Quantiles are log-normal around the fitted median with a per-hour spread
  from the residuals' interquartile range, so the 5%-95% band is the honest
  dispersion across past console launches, not a guessed width.

  Fallbacks keep every case valid: if the console subset is too small, the
  fit falls back to every comparable with a complete release day; if there is
  no usable comparable at all, it falls back to flat persistence with a
  widening spread. Any unexpected error on a case still writes a valid
  persistence forecast for that case instead of crashing.
"""

import json
import math
import os
import sys
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a helper
# module shipped beside this file would import. (This entry is one file.)
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]
HOURS = list(range(2, 25))  # the hours to forecast

# Tuned on leave-one-out over the console-only comparables (see README):
# median curve + per-hour size slope clearly beats flat persistence there.
MEDIAN_SMOOTH = True    # 3-point moving average on the median log-ratios
SLOPE_SHRINK = 0.85     # shrink the per-hour slopes 15% toward the pooled slope
SIGMA_MULT = 1.8        # widen the residual spread (LOO optimum ~2.0 on 6-game
                        # fits; 1.8 allows for the final's larger 11-game fit)
SIGMA_FLOOR = 0.12      # never claim an hour more precisely than this (log units)
MIN_CONSOLE = 4         # console subset smaller than this -> use all comparables
PERSIST_SIGMA = 0.15    # fallback spread, log units per sqrt hour


def _parse_ts(text):
    """ISO-8601 UTC timestamp -> (year, month, day, hour) tuple for arithmetic."""
    # Timestamps here are all whole hours in UTC; string slicing is enough
    # and avoids any datetime/timezone dependency.
    return (int(text[0:4]), int(text[5:7]), int(text[8:10]), int(text[11:13]))


def _shift_hour(stamp, hours):
    """Whole-hour timestamp shifted by `hours`, as an ISO string."""
    import datetime
    dt = datetime.datetime(stamp[0], stamp[1], stamp[2], stamp[3],
                           tzinfo=datetime.timezone.utc)
    dt = dt + datetime.timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:00:00Z")


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _quantile(ordered, q):
    """Linear-interpolated quantile of an already sorted list."""
    if not ordered:
        return float("nan")
    pos = q * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def _smooth3(values):
    """3-point moving average, endpoints averaged over the two available."""
    out = []
    n = len(values)
    for i in range(n):
        window = values[max(0, i - 1):min(n, i + 2)]
        out.append(sum(window) / len(window))
    return out


def _release_day(comp):
    """The comparable's 24 release-day hourly viewer counts, or None.

    The release day starts at `day_start`; hour 1 is day_start itself.
    Needs every hour present and positive, else the curve is unusable.
    """
    day_start = comp.get("day_start")
    hourly = comp.get("hourly") or []
    if not day_start or not hourly:
        return None
    by_from = {}
    for row in hourly:
        viewers = row.get("viewers")
        if isinstance(viewers, (int, float)) and viewers > 0:
            by_from[row.get("from")] = float(viewers)
    start = _parse_ts(day_start)
    series = []
    for h in range(24):
        stamp = _shift_hour(start, h)
        value = by_from.get(stamp)
        if value is None:
            return None
        series.append(value)
    return series


def _is_console_only(comp):
    """Console-only launch (no PC), not early-access contaminated."""
    platforms = str(comp.get("platforms") or "")
    if "PC" in platforms:
        return False
    unlock = str(comp.get("unlock") or "").lower()
    if "early-access" in unlock or "early access" in unlock:
        return False
    return True


def _usable_comparables(case):
    """(console_subset, all_usable): each a list of (name, v1, series24)."""
    target = str((case.get("game") or {}).get("name") or "")
    console = []
    every = []
    for comp in case.get("comparables") or []:
        name = str(comp.get("name") or "")
        if target and target.lower() in name.lower():
            continue  # the target game's own pre-release history is no launch
        series = _release_day(comp)
        if series is None or series[0] <= 0:
            continue
        entry = (name, series[0], series)
        every.append(entry)
        if _is_console_only(comp):
            console.append(entry)
    return console, every


def _fit(train):
    """Fit the median curve, per-hour size slopes and per-hour spreads.

    train: list of (name, v1, series24). Returns a dict the forecaster uses.
    """
    ref = _median([math.log(v1) for _, v1, _ in train])
    xs = [math.log(v1) - ref for _, v1, _ in train]
    x_min, x_max = min(xs), max(xs)
    medians = []
    slopes = []
    sigmas = []
    pooled_num = 0.0
    pooled_den = 0.0
    per_hour = []
    for h in range(1, 24):
        ratios = [math.log(series[h] / v1) for _, v1, series in train]
        medians.append(_median(ratios))
        mean_x = sum(xs) / len(xs)
        mean_y = sum(ratios) / len(ratios)
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ratios))
        den = sum((x - mean_x) ** 2 for x in xs)
        slope = num / den if den > 0 else 0.0
        slopes.append(slope)
        per_hour.append((ratios, slope))
        pooled_num += num
        pooled_den += den
    pooled = pooled_num / pooled_den if pooled_den > 0 else 0.0
    if MEDIAN_SMOOTH:
        medians = _smooth3(medians)
    slopes = _smooth3(slopes)
    slopes = [SLOPE_SHRINK * s + (1.0 - SLOPE_SHRINK) * pooled for s in slopes]
    for h in range(1, 24):
        ratios, _slope = per_hour[h - 1]
        fitted = [medians[h - 1] + slopes[h - 1] * x for x in xs]
        resid = sorted(r - f for r, f in zip(ratios, fitted))
        iqr = _quantile(resid, 0.75) - _quantile(resid, 0.25)
        sigma = max(SIGMA_FLOOR, iqr / 1.349) if iqr > 0 else SIGMA_FLOOR
        sigmas.append(sigma)
    sigmas = _smooth3(sigmas)
    sigmas = [s * SIGMA_MULT for s in sigmas]
    return {
        "ref": ref, "x_min": x_min, "x_max": x_max,
        "medians": medians, "slopes": slopes, "sigmas": sigmas,
    }


def _forecast_from_fit(p1, fit):
    """The 23 rows of quantiles for hour-1 print p1 under a fitted model."""
    x = math.log(p1) - fit["ref"]
    x = min(max(x, fit["x_min"]), fit["x_max"])  # no extrapolation past the data
    rows = []
    for i, h in enumerate(HOURS):
        centre = fit["medians"][i] + fit["slopes"][i] * x
        sigma = fit["sigmas"][i]
        quantiles = []
        for z in Z:
            value = p1 * math.exp(centre + z * sigma)
            value = min(max(value, 1.0), 1e9)
            quantiles.append(_round2(value))
        # Rounding can only break monotonicity by a cent; enforce it.
        for j in range(1, 5):
            if quantiles[j] < quantiles[j - 1]:
                quantiles[j] = quantiles[j - 1]
        rows.append({"hour": h, "q": quantiles})
    return {"hours": rows}


def _round2(value):
    """Round to 2 decimals, half up; whole numbers come back as ints."""
    scaled = value * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    rounded = whole / 100.0
    return int(rounded) if float(rounded).is_integer() else rounded


def _persistence(p1):
    """Flat fallback: every hour at the hour-1 print, widening spread."""
    rows = []
    for h in HOURS:
        quantiles = []
        for z in Z:
            value = min(max(p1 * math.exp(z * PERSIST_SIGMA * math.sqrt(h - 1)), 1.0), 1e9)
            quantiles.append(_round2(value))
        rows.append({"hour": h, "q": quantiles})
    return {"hours": rows}


def _hour1_print(case):
    """Hour 1's print, with defensive fallbacks (never crash the case)."""
    for row in case.get("known") or []:
        if row.get("hour") == 1:
            viewers = row.get("viewers")
            if isinstance(viewers, (int, float)) and viewers > 0:
                return float(viewers)
    history = case.get("history_hourly") or []
    if history:
        viewers = history[-1].get("viewers")
        if isinstance(viewers, (int, float)) and viewers > 0:
            return float(viewers)
    return 1.0


def forecast_case(case):
    """Forecast one case. Always returns a valid 23-row forecast."""
    p1 = max(1.0, _hour1_print(case))
    try:
        console, every = _usable_comparables(case)
        train = console if len(console) >= MIN_CONSOLE else every
        if len(train) >= MIN_CONSOLE:
            return _forecast_from_fit(p1, _fit(train))
    except Exception:
        pass  # any surprise in the fit must not void the case
    return _persistence(p1)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
