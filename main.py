"""Forecast GTA VI launch-day Twitch CCU, jam 2-24, 5 kuantil/jam.

Pendekatan (ditulis dari nol di sesi ini):
- Bentuk kurva launch-day dipelajari dari game console-only sebelumnya
  (tanpa PC, tanpa early access): tiap game diringkas sebagai log-ratio
  ln(viewers_jam / viewers_jam1) per jam.
- Pusat: regresi OLS per jam log-ratio terhadap ln(print jam 1) —
  game yang lebih besar punya kurva lebih datar (peak ratio lebih
  kecil). Slope diratakan antar jam tetangga (jendela 3) dan
  penyesuaiannya dibatasi +-1.5 unit log (guardrail ekstrapolasi).
- Spread: sigma per jam = max(0.30, 1.3 * IQR(residual) / 1.349),
  kuantil normal. Lantai 0.30 karena pergeseran level per game
  (satu game bisa bergeser sebagai satu blok sepanjang hari) tidak
  bisa diprediksi dari ukuran saja.

Validasi lokal (LOO 7 game console): loss 0.1528, typical miss 28.7%,
starter 0.3435. Parameter dipilih dari tengah dataran, bukan puncak.

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
MULT = 1.3
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


def _quantile(sorted_v, q):
    n = len(sorted_v)
    if n == 1:
        return sorted_v[0]
    pos = (n - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_v[lo] * (1.0 - frac) + sorted_v[hi] * frac


def _mean(v):
    return sum(v) / len(v)


def forecast(p1, train):
    """23 baris x 5 kuantil untuk jam 2..24."""
    p = max(float(p1), 1.0)
    if len(train) < 3:
        return starter(p)
    xs = [math.log(max(t[0], 1.0)) for t in train]
    rs = [[math.log(max(t[1][h], 1.0)) - math.log(max(t[1][0], 1.0))
           for h in range(1, 24)] for t in train]
    n = len(train)
    xbar = _mean(xs)
    x = math.log(p)
    ybar = [_mean([rs[i][h] for i in range(n)]) for h in range(23)]
    den = sum((v - xbar) ** 2 for v in xs)
    raw_b = []
    for h in range(23):
        num = sum((xs[i] - xbar) * (rs[i][h] - ybar[h])
                  for i in range(n))
        raw_b.append(num / den if den > 1e-12 else 0.0)
    # ratakan slope antar jam tetangga
    b = []
    for h in range(23):
        lo = max(0, h - 1)
        hi = min(22, h + 1)
        b.append(_mean(raw_b[lo:hi + 1]))
    # pusat + residual tiap game latih
    med = []
    resid = [[0.0] * 23 for _ in range(n)]
    for h in range(23):
        shift = b[h] * (x - xbar)
        shift = max(-GUARD, min(GUARD, shift))
        med.append(ybar[h] + shift)
    for i in range(n):
        for h in range(23):
            shift = b[h] * (xs[i] - xbar)
            shift = max(-GUARD, min(GUARD, shift))
            resid[i][h] = rs[i][h] - (ybar[h] + shift)
    # spread per jam
    sig = []
    for h in range(23):
        col = sorted(resid[i][h] for i in range(n))
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
