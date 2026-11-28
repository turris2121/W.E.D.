"""Labour tab: unemployment on ONE definition for every country, how national figures differ,
when definitions/methods changed, hidden unemployment, participation and minimum wages.

Source: ILOSTAT SDMX API (https://sdmx.ilo.org), free, no key.
  UNE_2EAP  ILO harmonised (modelled) unemployment rate, same ILO definition for every country
  UNE_DEAP  national labour-force-survey rate, with survey name, coverage notes and break flags
  UNE_DEA1  latest monthly/quarterly seasonally adjusted national rate
  LUU_XLU4  LU4: unemployed + time-related underemployed + potential labour force (national)
  EAP_2WAP  labour force participation rate (ILO harmonised)
  EAR_INEE  statutory monthly minimum wage (local currency, USD, PPP)
  EAR_EMTA  average monthly earnings (to compare the minimum wage against)
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from pathlib import Path

ILO = "https://sdmx.ilo.org/rest/data/ILO,{flow},1.0/{key}"
NOTES_FILE = Path(__file__).resolve().parent / "labour_notes.json"
ADULT, YOUTH = "AGE_YTHADULT_YGE15", "AGE_YTHADULT_Y15-24"


def _rows(session, flow, key, start):
    r = session.get(ILO.format(flow=flow, key=key), params={"startPeriod": start, "format": "csvfilewithlabels"},
                    timeout=300)
    if r.status_code == 404:  # SDMX "no results"
        return []
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def _num(v):
    try:
        return round(float(v), 3)
    except (TypeError, ValueError):
        return None


def fetch_labour(session) -> dict:
    year = dt.date.today().year
    out = {"harmonised": {}, "harmonised_youth": {}, "national": {}, "recent": {}, "lu4": {},
           "participation": {}, "min_wage": {}, "avg_earnings": {}}

    for r in _rows(session, "DF_UNE_2EAP_SEX_AGE_RT", f".A..SEX_T.{ADULT}+{YOUTH}", 2010):
        v = _num(r["OBS_VALUE"])
        if v is None:
            continue
        k = "harmonised" if r["AGE"] == ADULT else "harmonised_youth"
        out[k].setdefault(r["REF_AREA"], {})[r["TIME_PERIOD"]] = v

    # National survey series, keeping the metadata that reveals definition/method changes.
    for r in _rows(session, "DF_UNE_DEAP_SEX_AGE_RT", f".A..SEX_T.{ADULT}", 2005):
        v = _num(r["OBS_VALUE"])
        if v is None:
            continue
        out["national"].setdefault(r["REF_AREA"], []).append({
            "year": int(r["TIME_PERIOD"]), "value": v, "measure": r.get("Measure", ""),
            "source": r.get("SOURCE", ""), "note": r.get("NOTE_SOURCE", ""), "classif": r.get("NOTE_CLASSIF", ""),
            "indicator_note": r.get("NOTE_INDICATOR", ""), "break": r.get("OBS_STATUS") == "B",
        })

    for r in _rows(session, "DF_UNE_DEA1_SEX_AGE_RT", f".M+Q..SEX_T.{ADULT}", year - 2):
        v = _num(r["OBS_VALUE"])
        if v is not None:
            out["recent"].setdefault(r["REF_AREA"], []).append([r["TIME_PERIOD"], v])

    for r in _rows(session, "DF_LUU_XLU4_SEX_AGE_RT", f".A..SEX_T.{ADULT}", 2010):
        v = _num(r["OBS_VALUE"])
        if v is not None:
            out["lu4"].setdefault(r["REF_AREA"], {})[r["TIME_PERIOD"]] = v

    for r in _rows(session, "DF_EAP_2WAP_SEX_AGE_RT", f".A..SEX_T.{ADULT}", 2010):
        v = _num(r["OBS_VALUE"])
        if v is not None:
            out["participation"].setdefault(r["REF_AREA"], {})[r["TIME_PERIOD"]] = v

    for r in _rows(session, "DF_EAR_INEE_CUR_NB", ".A..", 2012):
        v = _num(r["OBS_VALUE"])
        if v is not None:
            cur = r["CUR"].replace("CUR_TYPE_", "").lower()  # lcu / usd / ppp
            d = out["min_wage"].setdefault(r["REF_AREA"], {}).setdefault(r["TIME_PERIOD"], {})
            d[cur] = v
            if cur == "lcu":
                d["note"] = r.get("NOTE_INDICATOR", "")

    for r in _rows(session, "DF_EAR_EMTA_SEX_CUR_NB", ".A..SEX_T.CUR_TYPE_LCU", 2012):
        v = _num(r["OBS_VALUE"])
        if v is not None:
            out["avg_earnings"].setdefault(r["REF_AREA"], {})[r["TIME_PERIOD"]] = v

    for s in out["recent"].values():
        s.sort()
    for s in out["national"].values():
        s.sort(key=lambda x: x["year"])
    if not out["harmonised"]:
        raise RuntimeError("ILO returned no harmonised unemployment data")
    return out


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
COVERAGE_PATTERNS = [
    (r"Urban areas only", "urban areas only"),
    (r"Main cities or metropolitan areas", "main cities only"),
    (r"excluding some areas", "excludes some regions"),
    (r"Rural areas only", "rural areas only"),
    (r"minimum age: (\d+)", "minimum age {0} (standard is 15)"),
    (r"maximum age: (\d+)", "maximum age {0} (older people excluded)"),
    (r"Excluding armed forces", "excludes armed forces"),
    (r"Excluding institutional population", "excludes people in institutions"),
]


def _coverage(note: str) -> list[str]:
    found = []
    for pat, label in COVERAGE_PATTERNS:
        m = re.search(pat, note or "", re.I)
        if m:
            if m.groups():
                if pat.startswith("minimum") and m.group(1) == "15":
                    continue
                found.append(label.format(*m.groups()))
            else:
                found.append(label)
    return found


def _short_survey(s: str) -> str:
    return re.sub(r"^[A-Z]+ - ", "", s or "").strip()


def _events(series: list[dict]) -> list[dict]:
    """Detect survey switches, coverage changes and flagged breaks in a national series."""
    ev = []
    prev = None
    for p in series:
        if p["break"]:
            ev.append({"year": p["year"], "type": "break in series", "auto": True,
                       "title": "Break in series",
                       "detail": "The ILO flags a break: the method, questionnaire or sample changed, so this year is not "
                                 "directly comparable with the years before."})
        if prev:
            if _short_survey(p["source"]) != _short_survey(prev["source"]):
                jump = p["value"] - prev["value"]
                ev.append({"year": p["year"], "type": "survey change", "auto": True,
                           "title": "Survey changed",
                           "detail": f"Source switched from \"{_short_survey(prev['source'])}\" to "
                                     f"\"{_short_survey(p['source'])}\". The rate moved {jump:+.1f} pp that year "
                                     f"({prev['value']:.1f}% → {p['value']:.1f}%), partly because of the switch."})
            c0, c1 = set(_coverage(prev["note"])), set(_coverage(p["note"]))
            if c0 != c1:
                added, removed = sorted(c1 - c0), sorted(c0 - c1)
                parts = []
                if added:
                    parts.append("now " + ", ".join(added))
                if removed:
                    parts.append("no longer " + ", ".join(removed))
                ev.append({"year": p["year"], "type": "coverage", "auto": True,
                           "title": "Coverage changed",
                           "detail": "Who is counted changed: " + "; ".join(parts) + "."})
            if p["year"] - prev["year"] > 1:
                ev.append({"year": p["year"], "type": "data gap", "auto": True,
                           "title": f"No data for {prev['year'] + 1}–{p['year'] - 1}" if p["year"] - prev["year"] > 2
                           else f"No data for {prev['year'] + 1}",
                           "detail": "The national survey was not published or not available for these years."})
        prev = p
    return ev


def _latest(d: dict | None, upto: int | None = None):
    if not d:
        return None, None
    ys = sorted((int(y), v) for y, v in d.items() if upto is None or int(y) <= upto)
    return (ys[-1] if ys else (None, None))


def build_labour(raw: dict, countries: list[dict]) -> dict:
    year = dt.date.today().year
    est_year = year - 1  # ILO harmonised figures for the current year and later are projections
    notes = {k: v for k, v in json.loads(NOTES_FILE.read_text()).items() if not k.startswith("_")}
    out = []
    for c in countries:
        iso = c["iso3"]
        h = raw["harmonised"].get(iso)
        hy, hv = _latest(h, est_year)
        if hv is None:
            continue
        proj_y, proj_v = _latest(h)
        nat = raw["national"].get(iso, [])
        last_nat = nat[-1] if nat else None
        same_year_h = h.get(str(last_nat["year"])) if last_nat and h else None
        gap = round(last_nat["value"] - same_year_h, 2) if last_nat and same_year_h is not None else None

        events = _events(nat)
        for n in notes.get(iso, []):
            events.append({**n, "auto": False})
        events.sort(key=lambda e: (e.get("year") or 0), reverse=True)

        coverage = _coverage(last_nat["note"]) if last_nat else []
        recent = raw["recent"].get(iso, [])
        lu4y, lu4 = _latest(raw["lu4"].get(iso))
        part = raw["participation"].get(iso, {})
        p_now = part.get(str(est_year))
        p_5 = part.get(str(est_year - 5))
        p_chg = round(p_now - p_5, 2) if p_now is not None and p_5 is not None else None
        hy5 = h.get(str(est_year - 5))

        # ---- comparability grade
        reasons = []
        score = 0
        if not last_nat:
            score += 2
            reasons.append("no national labour force survey data in ILO records")
        else:
            if year - last_nat["year"] > 3:
                score += 1
                reasons.append(f"latest national survey is from {last_nat['year']}")
            if any(x in coverage for x in ("urban areas only", "main cities only", "rural areas only")):
                score += 2
                reasons.append("national survey covers only part of the country (" + ", ".join(
                    x for x in coverage if "only" in x) + ")")
            elif coverage:
                score += 0.5
                reasons.append("coverage differs from the standard: " + ", ".join(coverage))
            if gap is not None and abs(gap) >= 2:
                score += 1
                reasons.append(f"national rate differs from the ILO harmonised rate by {gap:+.1f} pp")
        recent_changes = [e for e in events if (e.get("year") or 0) >= year - 10
                          and e["type"] in ("break in series", "survey change", "coverage", "redefinition", "suspension")]
        if recent_changes:
            score += 1 if len(recent_changes) < 3 else 2
            reasons.append(f"{len(recent_changes)} definition or method change(s) in the last 10 years")
        serious = [e for e in recent_changes if e["type"] in ("redefinition", "suspension")]
        if serious:
            score += 1
            reasons.append("official definition changed or publication suspended: " +
                           "; ".join(e["title"].lower() for e in serious))
        grade = "High" if score < 1 else "Medium" if score < 2 else "Low"

        # ---- hidden unemployment
        hidden = []
        if lu4 is not None and last_nat and lu4y and abs(lu4y - last_nat["year"]) <= 1:
            extra = lu4 - last_nat["value"]
            if extra >= 3:
                hidden.append(f"The broad measure (LU4: unemployed + underemployed + people who want work but are not "
                              f"searching) is {lu4:.1f}% in {lu4y}, {extra:.1f} pp above the headline.")
        if p_chg is not None and p_chg <= -2:
            hidden.append(f"Labour force participation fell {abs(p_chg):.1f} pp in 5 years: people who stop looking for "
                          f"work drop out of the unemployment count, which can make the rate look better than the job market.")
        if hy5 is not None and p_chg is not None and hv < hy5 - 1 and p_chg < -1:
            hidden.append("Unemployment fell while participation also fell, so part of the drop may be people leaving "
                          "the labour force rather than finding jobs.")

        # ---- minimum wage
        mw = raw["min_wage"].get(iso, {})
        mwy, mwd = _latest(mw)
        min_wage = None
        if mwd:
            lcu5 = (mw.get(str(mwy - 5)) or {}).get("lcu")
            avg = (raw["avg_earnings"].get(iso) or {}).get(str(mwy))
            ay, avg_any = _latest(raw["avg_earnings"].get(iso), mwy)
            avg_used, avg_year = (avg, mwy) if avg else (avg_any, ay)
            cur0 = c["economy"]["currencies"][0] if c["economy"].get("currencies") else {}
            usd, usd_note = mwd.get("usd"), None
            if usd is None and mwd.get("lcu") and cur0.get("per_usd"):
                usd, usd_note = round(mwd["lcu"] / cur0["per_usd"], 1), "converted at today's exchange rate"
            ppp_y, ppp_d = _latest({y: v for y, v in mw.items() if v.get("ppp") is not None})
            min_wage = {
                "year": mwy, "lcu": mwd.get("lcu"), "usd": usd, "usd_note": usd_note,
                "ppp": ppp_d.get("ppp") if ppp_d else None, "ppp_year": ppp_y,
                "currency": cur0.get("code"),
                "change_5y_pct": round((mwd["lcu"] / lcu5 - 1) * 100, 1) if lcu5 and mwd.get("lcu") else None,
                "pct_of_average": round(100 * mwd["lcu"] / avg_used, 1) if avg_used and mwd.get("lcu") else None,
                "average_year": avg_year if avg_used else None,
                "type": re.sub(r"\s*\|.*$", "", (mwd.get("note") or "").replace("Type of minimum wage: ", "")) or None,
                "history": [[y, v.get("usd")] for y, v in sorted(mw.items()) if v.get("usd") is not None],
            }

        out.append({
            "iso3": iso, "name": c["name"], "flag": c.get("flag"), "region": c.get("region"),
            "population": c["economy"].get("population"), "gdp_rank": c["economy"].get("gdp_rank"),
            "harmonised": hv, "harmonised_year": hy,
            "harmonised_projection": proj_v if proj_y and proj_y > hy else None,
            "harmonised_projection_year": proj_y if proj_y and proj_y > hy else None,
            "harmonised_5y_ago": hy5,
            "youth": _latest(raw["harmonised_youth"].get(iso), est_year)[1],
            "national": last_nat["value"] if last_nat else None,
            "national_year": last_nat["year"] if last_nat else None,
            "national_survey": _short_survey(last_nat["source"]) if last_nat else None,
            "gap": gap,
            "recent": recent[-1] if recent else None,
            "coverage": coverage,
            "grade": grade, "grade_reasons": reasons,
            "lu4": lu4, "lu4_year": lu4y,
            "participation": p_now, "participation_change_5y": p_chg,
            "hidden": hidden,
            "events": events,
            "min_wage": min_wage,
            "history": {
                "harmonised": sorted([int(y), v] for y, v in h.items()),
                "national": [[p["year"], p["value"]] for p in nat],
                "breaks": sorted({e["year"] for e in events if e.get("year") and e["type"] in
                                  ("break in series", "survey change", "coverage", "redefinition")}),
            },
        })
    out.sort(key=lambda r: (r["gdp_rank"] or 999))
    world = raw["harmonised"].get("X01") or {}
    return {
        "estimate_year": est_year,
        "world": {"rate": world.get(str(est_year)), "year": est_year},
        "countries": out,
    }
