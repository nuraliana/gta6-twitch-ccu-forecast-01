"""Forecast GTA VI launch-day Twitch CCU, jam 2-24, 5 kuantil/jam.

Ronde 2 (retest setelah Nur kurang puas dengan rebuild 0.1528).

Pendekatan (ditulis dari nol di sesi ini):
- Bentuk kurva launch-day dipelajari dari game console-only sebelumnya
  (tanpa PC, tanpa early access): tiap game diringkas sebagai log-ratio
  ln(viewers_jam / viewers_jam1) per jam.
- Pusat: MEDIAN dari tiga estimator per jam — OLS slope, Theil-Sen,
  dan LAD — masing-masing diratakan antar jam tetangga dan dibatasi
  +-1.5 unit log dari rata-rata (guardrail ekstrapolasi). Median dari
  tiga estimator lebih tahan terhadap satu game latih yang menyimpang
  daripada OLS saja (n latih hanya 6-11 game). Di LOO-7: 5 dari 7 game
  membaik vs OLS saja.
- Spread: sigma per jam = max(0.30, 1.1 * IQR(residual OLS)/1.349),
  kuantil normal. Lantai 0.30 mendominasi: pergeseran level per game
  (satu game bisa bergeser sebagai satu blok sepanjang hari) tidak
  bisa diprediksi dari ukuran saja.

Validasi lokal (LOO 7 game console): loss 0.1480, typical miss ~27%,
starter 0.3435. LOO semua 37 launch: 0.5381 (starter 0.9296).
Parameter dipilih dari tengah dataran, bukan puncak (mult 1.0-1.2
semua memberi 0.1479-0.1484 di LOO-7).

Stdlib saja, tanpa network, deterministik.
"""
import glob
import json
import math
import os
from datetime import datetime

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
Z = (-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722)
MULT = 1.1
FLOOR = 0.30
GUARD = 1.5


def _parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def day_curve(comp):
    """24 nilai viewers jam 1..24 hari rilis; None bila jam hilang."""
    ds = _parse_time(comp["day_start"])
    vals = {}
    for h in comp.get("hourly", []):
        try:
            t = _parse_time(h["from"])
        except Exception:
            continue
        k = int((t - ds).total_seconds() // 3600)
        if 0 <= k < 24:
            vals[k] = h["viewers"]
    return [vals.get(k) for k in range(24)]


def training_games(case):
    """Game latih: console-only, tanpa early access, kurva lengkap.
    Mengembalikan list (p1, curve24)."""
    out = []
    for c in case.get("comparables", []):
        name = c.get("name", "")
        if name.startswith("Grand Theft Auto VI category before release"):
            continue
        if "PC" in c.get("platforms", ""):
            continue
        if "early access" in c.get("unlock", "").lower():
            continue
        curve = day_curve(c)
        if curve[0] is None or curve[0] <= 0:
            continue
        if any(v is None or v <= 0 for v in curve):
            continue
        out.append((curve[0], curve))
    return out


def _mean(v):
    return sum(v) / len(v)


def _quantile(sorted_v, q):
    n = len(sorted_v)
    if n == 1:
        return sorted_v[0]
    pos = (n - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_v[lo] * (1.0 - frac) + sorted_v[hi] * frac


def _smooth(v, win=3):
    """Rata-rata bergerak jendela 3, tepi dipendekkan."""
    n = len(v)
    half = win // 2
    out = []
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n - 1, i + half)
        out.append(_mean(v[lo:hi + 1]))
    return out


def _logs(train):
    xs = [math.log(max(t[0], 1.0)) for t in train]
    rs = [[math.log(max(t[1][h], 1.0)) - math.log(max(t[1][0], 1.0))
           for h in range(1, 24)] for t in train]
    return xs, rs


def _clamp_shift(shift):
    return max(-GUARD, min(GUARD, shift))


def _centre_slope(xs, rs, x):
    """OLS per jam log-ratio ~ ln p1; slope diratakan antar jam."""
    n = len(xs)
    xbar = _mean(xs)
    ybar = [_mean([rs[i][h] for i in range(n)]) for h in range(23)]
    den = sum((v - xbar) ** 2 for v in xs)
    raw_b = []
    for h in range(23):
        num = sum((xs[i] - xbar) * (rs[i][h] - ybar[h])
                  for i in range(n))
        raw_b.append(num / den if den > 1e-12 else 0.0)
    b = _smooth(raw_b, 3)
    med = []
    for h in range(23):
        med.append(ybar[h] + _clamp_shift(b[h] * (x - xbar)))
    resid = [[0.0] * 23 for _ in range(n)]
    for i in range(n):
        for h in range(23):
            resid[i][h] = rs[i][h] - (ybar[h]
                                     + _clamp_shift(b[h] * (xs[i] - xbar)))
    return med, resid, ybar, b


def _theil_sen(xs, ys):
    """Slope median pairwise + intercept median."""
    n = len(xs)
    slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            if abs(xs[j] - xs[i]) > 1e-12:
                slopes.append((ys[j] - ys[i]) / (xs[j] - xs[i]))
    if not slopes:
        return 0.0, _mean(ys)
    s = sorted(slopes)
    m = len(s)
    b = s[m // 2] if m % 2 == 1 else 0.5 * (s[m // 2 - 1] + s[m // 2])
    inter = sorted([ys[i] - b * xs[i] for i in range(n)])
    a = inter[n // 2] if n % 2 == 1 else 0.5 * (inter[n // 2 - 1]
                                                + inter[n // 2])
    return a, b


def _lad(xs, ys):
    """Least absolute deviations per jam: grid slope -1..1 (langkah
    0.01), intercept = median(y - b*x), pilih biaya |resid| terkecil."""
    n = len(xs)
    best = None
    for b100 in range(-100, 101):
        b = b100 / 100.0
        res = sorted([ys[i] - b * xs[i] for i in range(n)])
        a = res[n // 2] if n % 2 == 1 else 0.5 * (res[n // 2 - 1]
                                                  + res[n // 2])
        cost = sum(abs(ys[i] - (a + b * xs[i])) for i in range(n))
        if best is None or cost < best[0]:
            best = (cost, a, b)
    return best[1], best[2]


def _centre_robust(xs, rs, x, kind):
    """Theil-Sen atau LAD per jam; prediksi dibatasi +-1.5 dari ybar,
    lalu diratakan antar jam."""
    n = len(xs)
    xbar = _mean(xs)
    med = []
    for h in range(23):
        ys = [rs[i][h] for i in range(n)]
        ybar = _mean(ys)
        if kind == "theil":
            a, b = _theil_sen(xs, ys)
        else:
            a, b = _lad(xs, ys)
        pred = a + b * x
        med.append(ybar + _clamp_shift(pred - ybar))
    return _smooth(med, 3)


def forecast(p1, train):
    """23 baris x 5 kuantil untuk jam 2..24."""
    p = max(float(p1), 1.0)
    if len(train) < 3:
        return starter(p)
    xs, rs = _logs(train)
    x = math.log(p)
    med_s, resid, _, _ = _centre_slope(xs, rs, x)
    med_t = _centre_robust(xs, rs, x, "theil")
    med_l = _centre_robust(xs, rs, x, "lad")
    med = []
    for h in range(23):
        vals = sorted([med_s[h], med_t[h], med_l[h]])
        med.append(vals[1])
    sig = []
    for h in range(23):
        col = sorted(resid[i][h] for i in range(len(resid)))
        iqr = _quantile(col, 0.75) - _quantile(col, 0.25)
        sig.append(max(FLOOR, MULT * iqr / 1.349))
    rows = []
    for h in range(23):
        q = [p * math.exp(med[h] + z * sig[h]) for z in Z]
        q = [min(max(v, 1.0), 1e9) for v in q]
        for k in range(1, 5):
            q[k] = max(q[k], q[k - 1])
        rows.append(q)
    return rows


def starter(p1):
    p = max(float(p1), 1.0)
    rows = []
    for h in range(2, 25):
        s = 0.15 * math.sqrt(h - 1)
        q = [p * math.exp(z * s) for z in Z]
        q = [min(max(v, 1.0), 1e9) for v in q]
        for k in range(1, 5):
            q[k] = max(q[k], q[k - 1])
        rows.append(q)
    return rows


def run_case(case):
    known = case.get("known") or []
    p1 = 1.0
    if known:
        p1 = known[0].get("viewers") or 1.0
    train = training_games(case)
    rows = forecast(p1, train)
    return {"hours": [{"hour": h + 2, "q": rows[h]} for h in range(23)]}


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(in_dir, "*.in"))):
        with open(path) as f:
            case = json.load(f)
        out = run_case(case)
        base = os.path.splitext(os.path.basename(path))[0]
        with open(os.path.join(out_dir, base + ".out"), "w") as f:
            json.dump(out, f)


if __name__ == "__main__":
    main()
