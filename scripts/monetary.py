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
# Fiscal policy + energy (source "macro")
# --------------------------------------------------------------------------- #
OECD_EO = ("https://sdmx.oecd.org/public/rest/data/OECD.ECO.MAD,DSD_EO@DF_EO,/{areas}.NLGQ+GGFLQ.A"
           "?startPeriod={start}&format=csvfilewithlabels")
DBNOMICS = "https://api.db.nomics.world/v22/series"
# BIS area -> OECD Economic Outlook area / ISO3 used by the IMF and World Bank
OECD_AREA = {"US": "USA", "XM": "EA17", "CN": "CHN", "JP": "JPN", "GB": "GBR", "KR": "KOR",
             "AU": "AUS", "CA": "CAN", "CH": "CHE", "IN": "IND", "BR": "BRA", "RU": "RUS", "MX": "MEX"}
WB_AREA = {**OECD_AREA, "XM": "EMU"}


def fetch_macro(session) -> dict:
    import datetime as dt
    year = dt.date.today().year
    fiscal: dict[str, dict] = {a: {"balance": {}, "debt": {}, "source": {}} for a in OECD_AREA}

    # 1) OECD Economic Outlook: general government net lending (NLGQ) and gross debt (GGFLQ), % of GDP
    inv = {v: k for k, v in OECD_AREA.items()}
    r = session.get(OECD_EO.format(areas="+".join(OECD_AREA.values()), start=year - 2), timeout=120)
    if r.ok:
        for row in csv.DictReader(io.StringIO(r.text)):
            a, v = inv.get(row.get("REF_AREA")), _num(row.get("OBS_VALUE"))
            if a and v is not None:
                key = "balance" if row["MEASURE"] == "NLGQ" else "debt"
                fiscal[a][key][row["TIME_PERIOD"]] = round(v, 2)
                fiscal[a]["source"][key] = "OECD Economic Outlook"

    # 2) IMF World Economic Outlook (via DBnomics) for anything the OECD lacks
    need = [a for a in OECD_AREA if a != "XM" and (not fiscal[a]["balance"] or not fiscal[a]["debt"])]
    if need:
        dims = json.dumps({"weo-country": [OECD_AREA[a] for a in need],
                           "weo-subject": ["GGXCNL_NGDP", "GGXWDG_NGDP"]})
        r = session.get(f"{DBNOMICS}/IMF/WEO:latest", params={"dimensions": dims, "observations": 1, "limit": 100}, timeout=120)
        r.raise_for_status()
        edition = None
        for s in r.json()["series"]["docs"]:
            iso, subj = s["series_code"].split(".")[:2]
            a = inv.get(iso)
            key = "balance" if subj == "GGXCNL_NGDP" else "debt"
            edition = s.get("dataset_code", "WEO")
            if a and not fiscal[a][key]:
                fiscal[a][key] = {p: round(v, 2) for p, v in zip(s["period"], s["value"])
                                  if v not in (None, "NA") and str(p) >= str(year - 2) and str(p) <= str(year + 2)}
                fiscal[a]["source"][key] = f"IMF World Economic Outlook ({edition.replace('WEO:', '')})"

    # 3) Energy prices: EIA Short-Term Energy Outlook (history + EIA projection), via DBnomics
    energy = {}
    for key, sid in (("brent", "BREPUUS.M"), ("gas_us", "NGHHUUS.M")):
        r = session.get(f"{DBNOMICS}/EIA/STEO/{sid}", params={"observations": 1}, timeout=120)
        r.raise_for_status()
        s = r.json()["series"]["docs"][0]
        energy[key] = [[p, round(v, 2)] for p, v in zip(s["period"], s["value"])
                       if isinstance(v, (int, float)) and p >= START]
    energy["last_actual"] = _shift(dt.date.today().strftime("%Y-%m"), 1)  # STEO: later months are projections

    # 4) Energy import dependence: net energy imports, % of energy use (negative = net exporter)
    dep = {}
    r = session.get(f"https://api.worldbank.org/v2/country/{';'.join(WB_AREA.values())}/indicator/EG.IMP.CONS.ZS",
                    params={"format": "json", "mrnev": 1, "per_page": 100}, timeout=90)
    r.raise_for_status()
    inv_wb = {v: k for k, v in WB_AREA.items()}
    for row in (r.json()[1] or []):
        code = row.get("countryiso3code") or row["country"]["id"]
        a = inv_wb.get(code)
        if a and row.get("value") is not None:
            dep[a] = {"value": round(row["value"], 1), "year": int(row["date"])}

    if not any(f["balance"] for f in fiscal.values()) or not energy.get("brent"):
        raise RuntimeError("macro: no fiscal or energy data")
    return {"fiscal": fiscal, "energy": energy, "energy_dependence": dep}


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


def _fiscal(f: dict | None, year: int, stance: str, bank_short: str) -> dict | None:
    """Fiscal impulse = rise in the deficit this year (pp of GDP). Positive = stimulus = IS shifts right."""
    if not f or not f.get("balance"):
        return None
    bal = {int(k): v for k, v in f["balance"].items()}
    debt = {int(k): v for k, v in f.get("debt", {}).items()}
    now, prev, nxt = bal.get(year), bal.get(year - 1), bal.get(year + 1)
    if now is None or prev is None:
        return None
    impulse = round(-(now - prev), 2)
    impulse_next = round(-(nxt - now), 2) if nxt is not None else None
    d = debt.get(year) or debt.get(year - 1)
    stance_f = "expansionary" if impulse >= 0.3 else "contractionary" if impulse <= -0.3 else "neutral"

    word = "deficit" if now < 0 else "surplus"
    s = (f"The government runs a {word} of {abs(now):.1f}% of GDP in {year} "
         f"({'deficit' if prev < 0 else 'surplus'} {abs(prev):.1f}% in {year - 1})")
    s += f", with public debt at {d:.0f}% of GDP. " if d is not None else ". "
    if stance_f == "expansionary":
        s += (f"Fiscal policy is expansionary (impulse {impulse:+.1f} pp of GDP): more spending or lower taxes "
              "shift the IS curve right, raising output, interest rates and inflation pressure. ")
    elif stance_f == "contractionary":
        s += (f"Fiscal policy is contractionary (impulse {impulse:+.1f} pp of GDP): consolidation shifts the IS curve left, "
              "cooling output and inflation. ")
    else:
        s += f"Fiscal policy is roughly neutral (impulse {impulse:+.1f} pp of GDP), so it barely moves the IS curve. "
    # Policy mix
    if stance_f == "expansionary" and stance == "tightening":
        s += f"The mix pulls in opposite directions: the government stimulates while the {bank_short} tightens, so rates must stay higher for longer. "
    elif stance_f == "contractionary" and stance == "easing":
        s += f"The mix is coordinated: fiscal tightening makes room for the {bank_short}'s rate cuts. "
    elif stance_f == "expansionary" and stance == "easing":
        s += "Both fiscal and monetary policy are stimulating demand, a strong push on output and inflation. "
    elif stance_f == "contractionary" and stance == "tightening":
        s += "Both fiscal and monetary policy are braking demand, a strong disinflationary mix. "
    if d is not None and d >= 100:
        s += "High debt limits room for further stimulus and makes the budget sensitive to interest rates."
    if impulse_next is not None and abs(impulse_next) >= 0.3:
        s += f" Plans for {year + 1} point to a {'further loosening' if impulse_next > 0 else 'tightening'} ({impulse_next:+.1f} pp)."
    return {"balance": now, "balance_prev": prev, "balance_next": nxt, "debt": d, "impulse": impulse,
            "impulse_next": impulse_next, "stance": stance_f, "text": s.strip(),
            "source": f.get("source", {}).get("balance")}


OIL_PASS_THROUGH = 0.03  # rule of thumb: +10% oil -> about +0.3 pp headline inflation


def _energy(energy: dict, dep: dict | None) -> dict | None:
    brent = [p for p in energy.get("brent", []) if p[0] <= energy.get("last_actual", "9999")]
    if not brent:
        return None
    p_now, oil = brent[-1]
    oil12 = _at(brent, _shift(p_now, 12))
    change = round((oil / oil12 - 1) * 100, 1) if oil12 else None
    fut = [p for p in energy["brent"] if p[0] > p_now]
    ahead = _at(energy["brent"], _shift(p_now, -12)) if fut else None
    outlook = round((ahead / oil - 1) * 100, 1) if ahead else None
    dval = dep["value"] if dep else None

    role = ("net energy importer" if dval is not None and dval > 10
            else "net energy exporter" if dval is not None and dval < -10 else "roughly energy self-sufficient")
    cpi_push = round(change * OIL_PASS_THROUGH, 1) if change is not None else None
    # IS effect: importers lose real income when oil rises, exporters gain (terms of trade).
    is_effect = round(-(change or 0) / 100 * (dval or 0) / 100, 3)

    s = f"Brent oil is ${oil:.0f} a barrel"
    s += f" ({change:+.0f}% in 12 months). " if change is not None else ". "
    if dval is not None:
        how = (f"{abs(dval):.0f}% of energy use {'imported' if dval > 0 else 'exported on top of home use'}"
               if abs(dval) >= 1 else "balanced energy trade")
        s += f"The economy is {'a ' if role.startswith('net') else ''}{role} ({how}, {dep['year']}). "
    shock = change is not None and abs(change) >= 15
    if shock and change > 0:
        if dval is not None and dval > 10:
            s += ("That is a negative supply shock: higher energy costs push prices up (cost-push inflation) "
                  "while squeezing real incomes, shifting the IS curve left, a stagflation risk. ")
        elif dval is not None and dval < -10:
            s += ("For an exporter it is a terms-of-trade gain: export revenue and government income rise, "
                  "shifting the IS curve right and supporting the currency, though fuel prices still rise at home. ")
        else:
            s += "Domestic production cushions the economy, but fuel and transport prices still rise. "
    elif shock and change < 0:
        s += ("Cheaper energy works like a positive supply shock for importers (lower costs, higher real incomes) "
              "and a loss of income for exporters. ")
    else:
        s += "Energy prices have been fairly stable, so they are not a major force right now. "
    if cpi_push is not None and abs(cpi_push) >= 0.2:
        s += f"Rule of thumb: about {cpi_push:+.1f} pp on headline inflation. "
    if outlook is not None:
        s += (f"The EIA projects Brent at ${ahead:.0f} in 12 months ({outlook:+.0f}%), so the energy effect on inflation "
              f"should {'fade' if (outlook < -5 and (change or 0) > 0) else 'build' if outlook > 5 else 'persist'}.")
    return {"oil": oil, "oil_period": p_now, "oil_change_12m": change, "oil_outlook_12m": outlook,
            "oil_in_12m": ahead, "import_dependence": dval, "role": role, "cpi_push": cpi_push,
            "is_effect": is_effect, "shock": "up" if shock and change > 0 else "down" if shock else "none",
            "text": s.strip()}


def _inflation(bank, cpi, position, stance, strength, fiscal=None, energy=None):
    target = bank["target"]
    band = bank.get("band")
    score = {"restrictive": -1, "accommodative": 1}.get(position, 0)
    score += {"tightening": -0.5, "easing": 0.5}.get(stance, 0)
    if strength is not None:
        score += -0.5 if strength >= 3 else 0.5 if strength <= -3 else 0
    if fiscal:
        score += 0.5 if fiscal["impulse"] >= 0.5 else -0.5 if fiscal["impulse"] <= -0.5 else 0
    if energy and energy["shock"] != "none":
        fading = (energy["oil_outlook_12m"] or 0) <= -10
        score += (0.5 if energy["shock"] == "up" else -0.5) * (0.5 if fading else 1)
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
    if fiscal and fiscal["impulse"] >= 0.5:
        up.append("fiscal stimulus")
    if fiscal and fiscal["impulse"] <= -0.5:
        down.append("fiscal consolidation")
    if energy and energy["shock"] == "up":
        up.append(f"higher oil prices ({energy['oil_change_12m']:+.0f}% y/y)")
    if energy and energy["shock"] == "down":
        down.append(f"lower oil prices ({energy['oil_change_12m']:+.0f}% y/y)")
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


# --------------------------------------------------------------------------- #
# Rate outlook: why a bank holds, and what could make it move fast
# --------------------------------------------------------------------------- #
LABOUR_ISO = {"US": ["USA"], "XM": ["DEU", "FRA", "ITA", "ESP"], "CN": ["CHN"], "JP": ["JPN"], "GB": ["GBR"],
              "IN": ["IND"], "BR": ["BRA"], "CA": ["CAN"], "RU": ["RUS"], "KR": ["KOR"], "AU": ["AUS"],
              "MX": ["MEX"], "CH": ["CHE"]}
EMERGING = {"BR", "IN", "MX", "RU", "CN"}


def _unemployment(labour_recent: dict, area: str) -> dict | None:
    """Latest monthly (else quarterly) unemployment and its change over ~6 months (euro area: big-4 average)."""
    vals = []
    for iso in LABOUR_ISO.get(area, []):
        s = labour_recent.get(iso) or []
        monthly = [p for p in s if "-M" in p[0]]
        quarterly = [p for p in s if "-Q" in p[0]]
        if len(monthly) >= 7:
            vals.append((monthly[-1][0], monthly[-1][1], monthly[-1][1] - monthly[-7][1]))
        elif len(quarterly) >= 3:
            vals.append((quarterly[-1][0], quarterly[-1][1], quarterly[-1][1] - quarterly[-3][1]))
    if not vals:
        return None
    period = max(v[0] for v in vals)
    return {"rate": round(sum(v[1] for v in vals) / len(vals), 2),
            "change_6m": round(sum(v[2] for v in vals) / len(vals), 2),
            "period": period.replace("-M", "-").replace("-Q", " Q"),
            "label": "euro area (DE, FR, IT, ES average)" if area == "XM" else None}


def rate_outlook(area, bank, rate, d3, cpi, cpi_3m_chg, real, neutral, position, strength, fx_1m,
                 fiscal, energy, unemp, gap_vs_us, is_us) -> dict:
    target = bank["target"]
    lo, hi = bank["band"] if bank.get("band") else (target - 0.5, target + 0.5)
    hike, cut, hold = [], [], []

    # --- inflation
    if cpi is not None:
        if cpi > hi and (cpi_3m_chg is None or cpi_3m_chg >= -0.1):
            hike.append(f"Inflation is {cpi:.1f}%, above target ({bank['target_note']}) and not coming down")
        elif cpi > hi:
            hold.append(f"Inflation is {cpi:.1f}%, still above target but falling ({cpi_3m_chg:+.1f} pp in 3 months)")
        elif cpi < lo:
            cut.append(f"Inflation is {cpi:.1f}%, below target ({bank['target_note']})")
        else:
            if cpi_3m_chg is not None and cpi_3m_chg < -0.3:
                cut.append(f"Inflation is {cpi:.1f}%, near target and falling")
            elif cpi_3m_chg is not None and cpi_3m_chg >= 0.5:
                hike.append(f"Inflation is {cpi:.1f}%, still in range but rising fast ({cpi_3m_chg:+.1f} pp in 3 months)")
            else:
                hold.append(f"Inflation is {cpi:.1f}%, close to target ({bank['target_note']})")
    # --- policy stance in real terms
    if real is not None:
        if position == "accommodative" and cpi is not None and cpi > hi:
            hike.append(f"The real rate ({real:+.1f}%) is below neutral while inflation is above target, so policy is still loose")
        elif position == "restrictive" and cpi is not None and cpi <= hi:
            cut.append(f"The real rate ({real:+.1f}%) is well above neutral (~{neutral:g}%), so policy is tight with inflation near target")
        elif position == "restrictive":
            hold.append(f"Policy is already tight in real terms ({real:+.1f}%), so the bank can wait for it to work")
    # --- recent move
    if d3 is not None and abs(d3) >= 0.25:
        hold.append(f"It moved rates {d3:+.2f} pp in the last 3 months and usually waits to see the effect")
    # --- labour market
    if unemp:
        if unemp["change_6m"] >= 0.5:
            cut.append(f"Unemployment rose {unemp['change_6m']:+.1f} pp in about 6 months, to {unemp['rate']:.1f}% (a recession warning)")
        elif unemp["change_6m"] <= -0.3 and cpi is not None and cpi > hi:
            hike.append(f"Unemployment fell to {unemp['rate']:.1f}% while inflation is above target (a tight labour market)")
        elif abs(unemp["change_6m"]) < 0.3:
            hold.append(f"The job market is stable (unemployment {unemp['rate']:.1f}%)")
    # --- currency
    if fx_1m is not None and fx_1m <= -5:
        hike.append(f"The {bank['currency']} fell {abs(fx_1m):.1f}% against the dollar in the last month, a sudden drop that often forces a hike")
    elif strength is not None:
        if strength <= -5:
            hike.append(f"The {'dollar' if is_us else bank['currency']} weakened {abs(strength):.1f}% in a year, raising import prices")
        elif strength >= 5:
            cut.append(f"The {'dollar' if is_us else bank['currency']} strengthened {strength:.1f}% in a year, making imports cheaper")
    # --- energy
    if energy and energy["shock"] == "up":
        dep = energy.get("import_dependence") or 0
        fading = (energy.get("oil_outlook_12m") or 0) <= -10
        if dep > 10 and not fading:
            hike.append(f"Oil is up {energy['oil_change_12m']:.0f}% in a year, pushing up costs for an energy importer")
        elif fading and dep > 10:
            hold.append(f"Oil is up {energy['oil_change_12m']:.0f}%, but the EIA expects prices to fall, so the bank can look through it")
    elif energy and energy["shock"] == "down":
        cut.append(f"Oil is down {abs(energy['oil_change_12m']):.0f}% in a year, lowering costs")
    # --- fiscal
    if fiscal:
        if fiscal["impulse"] >= 0.5:
            hike.append(f"The government is adding stimulus ({fiscal['impulse']:+.1f} pp of GDP), which adds demand")
        elif fiscal["impulse"] <= -0.5:
            cut.append(f"The government is tightening its budget ({fiscal['impulse']:+.1f} pp of GDP), which cools demand")

    diff = len(hike) - len(cut)
    if hike and cut:
        hold.append("Signals point both ways, so waiting is the safest option")
    if diff >= 2:
        verdict, lean = "Pressure to raise rates", "up"
    elif diff <= -2:
        verdict, lean = "Room to cut rates", "down"
    else:
        verdict = "Likely to hold" + (", leaning to a hike" if diff == 1 else ", leaning to a cut" if diff == -1 else "")
        lean = "hold"

    # --- triggers: what could make it move fast
    trig = []
    if cpi is not None:
        trig.append({"variable": "Inflation (CPI, y/y)", "now": f"{cpi:.1f}%" + (f" ({cpi_3m_chg:+.1f} pp in 3 mo)" if cpi_3m_chg is not None else ""),
                     "hike": f"Rises above {hi + 0.5:.1f}% or keeps climbing for several months",
                     "cut": f"Falls below {lo:.1f}%",
                     "status": "hike" if cpi > hi + 0.5 else "cut" if cpi < lo else ("near" if cpi > hi or cpi < lo + 0.3 else "")})
    if unemp:
        trig.append({"variable": "Unemployment" + (f" ({unemp['label']})" if unemp.get("label") else ""),
                     "now": f"{unemp['rate']:.1f}% ({unemp['period']}), {unemp['change_6m']:+.1f} pp in ~6 mo",
                     "hike": "Falls fast while inflation is above target (overheating)",
                     "cut": "Rises 0.5 pp or more within 6 months (recession signal)",
                     "status": "cut" if unemp["change_6m"] >= 0.5 else "near" if unemp["change_6m"] >= 0.3 else ""})
    else:
        trig.append({"variable": "Unemployment", "now": "no monthly data",
                     "hike": "Labour shortages push wages up fast", "cut": "Lay-offs spread / unemployment jumps", "status": ""})
    cur = "dollar" if is_us else bank["currency"]
    trig.append({"variable": f"Exchange rate ({cur})",
                 "now": (f"{strength:+.1f}% in 12 mo" if strength is not None else "—") + (f", {fx_1m:+.1f}% last month" if fx_1m is not None else ""),
                 "hike": f"The {cur} drops 5%+ in a few weeks (imported inflation, money leaving the country)" +
                         (" — emerging markets often hike in emergency meetings" if area in EMERGING else ""),
                 "cut": f"The {cur} strengthens sharply, cheapening imports",
                 "status": "hike" if fx_1m is not None and fx_1m <= -5 else "near" if fx_1m is not None and fx_1m <= -3 else ""})
    if energy:
        oil = energy["oil"]
        trig.append({"variable": "Oil price (Brent)", "now": f"${oil:.0f} ({energy['oil_change_12m']:+.0f}% in 12 mo)",
                     "hike": f"Jumps above ${oil * 1.25:.0f} and starts feeding wages and prices" +
                             (" (hits an importer hard)" if (energy.get("import_dependence") or 0) > 10 else ""),
                     "cut": f"Falls below ${oil * 0.75:.0f} or demand collapses",
                     "status": "near" if energy["shock"] == "up" else ""})
    if is_us:
        trig.append({"variable": "Financial markets", "now": "—",
                     "hike": "Inflation expectations jump in markets or surveys",
                     "cut": "Bank failures or a market crash: emergency cuts and liquidity (as in 2008 and March 2020)", "status": ""})
    else:
        trig.append({"variable": "The Fed (US rates)", "now": f"gap vs Fed {gap_vs_us:+.2f} pp" if gap_vs_us is not None else "—",
                     "hike": f"The Fed hikes, narrowing the gap and pressuring the {bank['currency']}",
                     "cut": "The Fed cuts, giving room to follow without weakening the currency", "status": ""})
    if fiscal:
        trig.append({"variable": "Government budget", "now": f"deficit {abs(fiscal['balance']):.1f}% of GDP, impulse {fiscal['impulse']:+.1f} pp",
                     "hike": "A big new spending package or tax cut adds demand",
                     "cut": "Sharp budget cuts or a fiscal crisis hits growth",
                     "status": "near" if fiscal["impulse"] >= 0.5 else ""})
    if area == "RU":
        trig.append({"variable": "Sanctions / capital flight", "now": "—",
                     "hike": "New sanctions or a run on the rouble (in Feb 2022 the CBR raised rates from 9.5% to 20% overnight)",
                     "cut": "Easing of sanctions and a stable rouble", "status": ""})
    elif not is_us:
        trig.append({"variable": "Financial stress", "now": "—",
                     "hike": "Capital flight or a currency crisis" if area in EMERGING else "Rarely a reason to hike",
                     "cut": "A banking or market crisis: emergency cuts and liquidity support", "status": ""})
    return {"verdict": verdict, "lean": lean, "hike": hike, "cut": cut, "hold": hold, "triggers": trig,
            "unemployment": unemp}


def build_central_banks(bis: dict, countries: list[dict], macro: dict | None = None,
                        labour_raw: dict | None = None) -> list[dict]:
    import datetime as dt
    year = dt.date.today().year
    macro = macro or {}
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
        fiscal = _fiscal(macro.get("fiscal", {}).get(area), year, stance, bank["short"])
        energy = (_energy(macro["energy"], macro.get("energy_dependence", {}).get(area))
                  if macro.get("energy") else None)
        infl = _inflation(bank, cpi, position, stance, strength, fiscal, energy)
        cpi_3 = _at(d["cpi"], _shift(cp, 3)) if cp else None
        cpi_3m_chg = round(cpi - cpi_3, 2) if cpi is not None and cpi_3 is not None else None
        fx_1m = None
        if is_us and others:
            pass  # dollar 1-month move not tracked separately
        elif fp and fx:
            fx_prev = _at(d["fx"], _shift(fp, 1))
            fx_1m = round((fx_prev / fx - 1) * 100, 2) if fx_prev else None
        unemp = _unemployment((labour_raw or {}).get("recent", {}), area)
        outlook = rate_outlook(area, bank, rate, d3, cpi, cpi_3m_chg, real, neutral, position, strength, fx_1m,
                               fiscal, energy, unemp, diff if not is_us else None, is_us)
        # IS shift (schematic units, pp of GDP-ish): fiscal impulse + energy terms-of-trade effect
        is_shift = round((fiscal["impulse"] if fiscal else 0) + (energy["is_effect"] * 4 if energy else 0), 2)

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
            "is_shift": is_shift,
            "outlook": outlook,
            "cpi_3m_change": cpi_3m_chg,
            "fiscal": fiscal,
            "energy": energy,
            "islm_text": _islm_text(stance, d12, real, neutral, position),
            "currency_text": _currency_text(bank, is_us, diff, diff_change, strength),
            "inflation": infl,
            "history": {k: [x for x in d[k] if x[0] >= start] for k in ("rates", "cpi", "fx")},
        })
    out.sort(key=lambda b: -b["world_gdp_share"])
    return out
