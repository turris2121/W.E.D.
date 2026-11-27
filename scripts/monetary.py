"""Central banks: fetch BIS data and turn it into rule-based IS-LM / inflation notes.

Everything here is a transparent heuristic, not a forecast:
  stance     12-month change in the policy rate
  position   real rate (policy rate - CPI inflation) vs an assumed neutral real rate
  IS-LM      tightening shifts LM up/left (r up, Y down); easing shifts it down/right
  currency   open-economy IS-LM (Mundell-Fleming): rate gap vs the US + 12-month FX trend
  inflation  restrictive policy / stronger currency push inflation down over 12-18 months
"""
from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path

BANKS_FILE = Path(__file__).resolve().parent / "central_banks.json"
BIS = "https://stats.bis.org/api/v2/data/dataflow/BIS/{flow}/1.0/{key}"
START = "2023-01"


def load_banks() -> dict:
    return {k: v for k, v in json.loads(BANKS_FILE.read_text()).items() if not k.startswith("_")}


def _bis_csv(session, flow: str, key: str) -> list[dict]:
    r = session.get(BIS.format(flow=flow, key=key), params={"startPeriod": START, "format": "csv"}, timeout=90)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def fetch_bis(session) -> dict:
    areas = list(load_banks())
    joined = "+".join(areas)
    out = {a: {"rates": [], "cpi": [], "fx": []} for a in areas}
    for field, flow, key in (
        ("rates", "WS_CBPOL", f"M.{joined}"),
        ("cpi", "WS_LONG_CPI", f"M.{joined}.771"),          # 771 = year-on-year % change
        ("fx", "WS_XRU", f"M.{'+'.join(a for a in areas if a != 'US')}..A"),  # A = monthly average
    ):
        for row in _bis_csv(session, flow, key):
            a, v = row.get("REF_AREA"), _num(row.get("OBS_VALUE"))
            if a in out and v is not None:
                out[a][field].append([row["TIME_PERIOD"], round(v, 4)])
    for a in out.values():
        for f in a.values():
            f.sort()
    if not any(a["rates"] for a in out.values()):
        raise RuntimeError("BIS returned no policy rates")
    return out


# --------------------------------------------------------------------------- #
# Series helpers (periods are "YYYY-MM")
# --------------------------------------------------------------------------- #
def _shift(period: str, months: int) -> str:
    y, m = map(int, period.split("-"))
    t = y * 12 + (m - 1) - months
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def _last(s):
    return (s[-1][0], s[-1][1]) if s else (None, None)


def _at(s, period):
    """Value at `period`, or the latest one before it."""
    best = None
    for p, v in s:
        if p <= period:
            best = v
        else:
            break
    return best


def _pp(v):
    return f"{v:+.2f} pp"


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
def _stance(d12, d3):
    if d12 is None:
        return "unknown", ""
    if d12 >= 0.25:
        s = "tightening"
        note = "hikes paused in the last 3 months" if d3 is not None and abs(d3) < 0.01 else "still raising rates"
    elif d12 <= -0.25:
        s = "easing"
        note = "cuts paused in the last 3 months" if d3 is not None and abs(d3) < 0.01 else "still cutting rates"
    else:
        s = "holding"
        note = "rate unchanged over the year" if abs(d12) < 0.01 else "only small moves over the year"
        if d3 is not None and abs(d3) >= 0.25:
            note = "has just started " + ("raising" if d3 > 0 else "cutting")
    return s, note


def _position(real, neutral):
    if real is None:
        return "unknown"
    if real > neutral + 0.5:
        return "restrictive"
    if real < neutral - 0.5:
        return "accommodative"
    return "neutral"


def _islm_text(stance, d12, real, neutral, position):
    if stance == "tightening":
        s = (f"The policy rate rose {abs(d12):.2f} pp in 12 months, so the LM curve shifts up/left: "
             "money is tighter, borrowing costs rise, investment and spending cool. "
             "The new equilibrium has a higher interest rate (r) and lower output (Y).")
    elif stance == "easing":
        s = (f"The policy rate fell {abs(d12):.2f} pp in 12 months, so the LM curve shifts down/right: "
             "money is looser, borrowing is cheaper, investment and spending pick up. "
             "The new equilibrium has a lower interest rate (r) and higher output (Y).")
    else:
        s = ("The policy rate barely moved, so the LM curve stays roughly where it was; "
             "changes in output now come mainly from the IS side (fiscal policy, exports, confidence).")
    if real is not None:
        s += (f" With a real rate of {real:+.1f}% against an assumed neutral of about {neutral:g}%, "
              f"policy is {position}")
        s += {"restrictive": ": it is still holding demand back.",
              "accommodative": ": it is still pushing demand up.",
              "neutral": ": it is neither braking nor boosting demand much."}.get(position, ".")
    return s


def _move(subject, strength, against):
    if abs(strength) < 0.5:
        return f"{subject} has barely moved {against} over 12 months."
    word = "strengthened" if strength > 0 else "weakened"
    return f"{subject} has {word} {abs(strength):.1f}% {against} over 12 months."


def _currency_text(bank, is_us, diff, diff_change, strength):
    cur = bank["currency"]
    parts = []
    if is_us:
        if diff is not None:
            parts.append(f"US rates are {_pp(diff)} versus the average of the other major central banks.")
        if strength is not None:
            parts.append(_move("The dollar", strength, "on average against their currencies"))
        parts.append("Because the dollar is the world's reserve currency, Fed moves spill over into every other "
                     "economy's financing costs and exchange rate.")
    else:
        if diff is not None:
            parts.append(f"{bank['short']} rates are {_pp(diff)} versus the Fed.")
            if diff_change is not None and abs(diff_change) >= 0.25:
                if diff_change > 0:
                    parts.append(f"Over the year the gap moved {diff_change:.2f} pp in the {cur}'s favour, which tends to "
                                 f"attract capital and support the {cur} (Mundell-Fleming).")
                else:
                    parts.append(f"Over the year the gap moved {abs(diff_change):.2f} pp against the {cur}, which tends to "
                                 f"push capital out and weigh on the {cur} (Mundell-Fleming).")
        if strength is not None:
            parts.append(_move(f"The {cur}", strength, "against the USD"))
    if strength is not None:
        if strength >= 3:
            parts.append("A stronger currency makes imports cheaper, which pulls inflation down.")
        elif strength <= -3:
            parts.append("A weaker currency makes imports dearer, adding imported inflation.")
        else:
            parts.append("The exchange rate has been fairly stable, so its effect on inflation is small.")
    return " ".join(parts)


def _inflation(bank, cpi, position, stance, strength):
    target = bank["target"]
    band = bank.get("band")
    score = {"restrictive": -1, "accommodative": 1}.get(position, 0)
    score += {"tightening": -0.5, "easing": 0.5}.get(stance, 0)
    if strength is not None:
        score += -0.5 if strength >= 3 else 0.5 if strength <= -3 else 0
    direction = "down" if score <= -1 else "up" if score >= 1 else "stable"
    arrow = {"down": "↓", "up": "↑", "stable": "→"}[direction]

    if cpi is None:
        return {"direction": direction, "arrow": arrow, "text": "No recent inflation data."}
    lo, hi = (band if band else (target - 0.5, target + 0.5))
    where = "above" if cpi > hi else "below" if cpi < lo else "close to"
    s = f"Inflation is {cpi:.1f}%, {where} target ({bank['target_note']}). "
    down, up = [], []
    if position == "restrictive":
        down.append("restrictive real rates")
    if position == "accommodative":
        up.append("loose real rates")
    if stance == "tightening":
        down.append("rate hikes over the past year")
    if stance == "easing":
        up.append("rate cuts over the past year")
    if strength is not None and strength >= 3:
        down.append("a stronger currency")
    if strength is not None and strength <= -3:
        up.append("a weaker currency (imported inflation)")
    if down:
        s += "Pushing inflation down: " + ", ".join(down) + ". "
    if up:
        s += "Pushing it up: " + ", ".join(up) + ". "
    if direction == "down":
        s += ("Over the next 12–18 months the rules point to inflation falling further below target (watch for deflation risk)."
              if where == "below" else "Over the next 12–18 months the rules point to inflation easing toward target.")
    elif direction == "up":
        s += ("Over the next 12–18 months the rules point to inflation rising further above target."
              if where == "above" else "Over the next 12–18 months the rules point to inflation drifting up.")
    else:
        s += "Over the next 12–18 months the rules point to inflation staying roughly where it is."
    return {"direction": direction, "arrow": arrow, "text": s}


def build_central_banks(bis: dict, countries: list[dict]) -> list[dict]:
    banks = load_banks()
    by_iso = {c["iso3"]: c for c in countries}
    us = bis.get("US", {})
    us_p, us_rate = _last(us.get("rates", []))

    # Rate of every bank 12 months ago, for the gap-vs-US and US-vs-others comparisons.
    snap = {}
    for a, d in bis.items():
        p, r = _last(d["rates"])
        snap[a] = (r, _at(d["rates"], _shift(p, 12)) if p else None)

    # USD strength = average depreciation of the other currencies against the USD.
    others = []
    for a, d in bis.items():
        if a == "US" or not d["fx"]:
            continue
        p, fx = _last(d["fx"])
        fx12 = _at(d["fx"], _shift(p, 12))
        if fx and fx12:
            others.append((fx / fx12 - 1) * 100)
    usd_strength = sum(others) / len(others) if others else None
    other_rates = [r for a, (r, _) in snap.items() if a != "US" and r is not None]
    other_rates12 = [r12 for a, (_, r12) in snap.items() if a != "US" and r12 is not None]

    out = []
    for area, bank in banks.items():
        d = bis.get(area, {"rates": [], "cpi": [], "fx": []})
        rp, rate = _last(d["rates"])
        r3 = _at(d["rates"], _shift(rp, 3)) if rp else None
        r12 = _at(d["rates"], _shift(rp, 12)) if rp else None
        d3 = round(rate - r3, 3) if rate is not None and r3 is not None else None
        d12 = round(rate - r12, 3) if rate is not None and r12 is not None else None
        cp, cpi = _last(d["cpi"])
        cpi12 = _at(d["cpi"], _shift(cp, 12)) if cp else None
        real = round(rate - cpi, 2) if rate is not None and cpi is not None else None
        neutral = bank.get("neutral_real_rate", 0.5)

        is_us = area == "US"
        fp, fx = _last(d["fx"])
        fx12 = _at(d["fx"], _shift(fp, 12)) if fp else None
        if is_us:
            strength = round(usd_strength, 2) if usd_strength is not None else None
            diff = round(rate - sum(other_rates) / len(other_rates), 2) if rate is not None and other_rates else None
            diff12 = (round(r12 - sum(other_rates12) / len(other_rates12), 2)
                      if r12 is not None and other_rates12 else None)
        else:
            strength = round((fx12 / fx - 1) * 100, 2) if fx and fx12 else None
            diff = round(rate - us_rate, 2) if rate is not None and us_rate is not None else None
            us12 = snap.get("US", (None, None))[1]
            diff12 = round(r12 - us12, 2) if r12 is not None and us12 is not None else None
        diff_change = round(diff - diff12, 2) if diff is not None and diff12 is not None else None

        stance, stance_note = _stance(d12, d3)
        position = _position(real, neutral)
        infl = _inflation(bank, cpi, position, stance, strength)

        covered = [by_iso[i] for i in bank["countries"] if i in by_iso]
        share = round(sum(c["economy"].get("world_gdp_share") or 0 for c in covered), 2)
        flags = "🇪🇺" if area == "XM" else "".join(c.get("flag") or "" for c in covered)

        start = _shift(rp, 23) if rp else START
        out.append({
            "area": area, **{k: bank[k] for k in ("name", "short", "currency", "target", "band", "target_note", "mandate", "url")},
            "countries": bank["countries"], "flag": flags, "world_gdp_share": share,
            "rate": rate, "rate_period": rp, "rate_change_3m": d3, "rate_change_12m": d12,
            "cpi": cpi, "cpi_period": cp, "cpi_12m_ago": cpi12, "real_rate": real, "neutral_real_rate": neutral,
            "fx": fx, "fx_period": fp, "currency_strength_12m": strength,
            "rate_gap_vs_us": diff, "rate_gap_change_12m": diff_change,
            "stance": stance, "stance_note": stance_note, "position": position,
            "lm_shift": d12 or 0,
            "islm_text": _islm_text(stance, d12, real, neutral, position),
            "currency_text": _currency_text(bank, is_us, diff, diff_change, strength),
            "inflation": infl,
            "history": {k: [x for x in d[k] if x[0] >= start] for k in ("rates", "cpi", "fx")},
        })
    out.sort(key=lambda b: -b["world_gdp_share"])
    return out
