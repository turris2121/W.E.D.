#!/usr/bin/env python3
"""Fetch every data source, merge per country, and write site/data/*.json.

Each source is cached in data/raw/<name>.json. A source is only re-fetched
when its cache is older than MAX_AGE_HOURS (or with --force). If a fetch
fails, the previous cache is used, so the dashboard never loses data.

Usage:  python scripts/fetch_all.py [--force] [--only fx,worldbank,...]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import requests

import monetary  # scripts/monetary.py (central banks, IS-LM rules)
import trade  # scripts/trade.py (trade flows, tariffs, taxes)
import labour  # scripts/labour.py (harmonised unemployment, definition changes, minimum wages)
import food  # scripts/food.py (FAOSTAT diets, self-sufficiency, food import partners)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "site" / "data"
QUERIES = Path(__file__).resolve().parent / "queries"
OVERRIDES = Path(__file__).resolve().parent / "overrides.json"

UA = "world-dashboard/1.0 (+https://github.com; open-data dashboard)"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = UA

MAX_AGE_HOURS = {
    "countries": 24 * 7,
    "worldbank": 24,
    "fx": 12,
    "politics": 24,
    "elections": 24,
    "ipu": 24 * 7,
    "bis": 24,
    "macro": 24,           # OECD/IMF fiscal, EIA energy, World Bank energy dependence
    "trade": 24,           # daily check; trade.py only re-downloads economies older than 30 days
    "tariffs": 24 * 7,
    "us_customs": 24,
    "services": 24 * 7,
    "census": 24,
    "labour": 24 * 7,      # ILOSTAT updates monthly at most; weekly is plenty
    "food": 24 * 7,        # FAOSTAT bulk files; re-downloaded only when FAO publishes a new version
}

SOURCE_URLS = {
    "countries": "https://www.wikidata.org + https://data.worldbank.org",
    "worldbank": "https://data.worldbank.org",
    "fx": "https://www.exchangerate-api.com (open.er-api.com)",
    "politics": "https://www.wikidata.org",
    "elections": "https://www.wikidata.org",
    "ipu": "https://data.ipu.org",
    "bis": "https://data.bis.org",
    "macro": "https://data-explorer.oecd.org + https://db.nomics.world (IMF WEO, EIA STEO) + https://data.worldbank.org",
    "trade": "https://comtradeplus.un.org",
    "tariffs": "https://data.worldbank.org + https://data-explorer.oecd.org",
    "us_customs": "https://fiscaldata.treasury.gov + https://comtradeplus.un.org",
    "services": "https://data-explorer.oecd.org (OECD-WTO BaTIS)",
    "census": "https://www.census.gov/foreign-trade",
    "labour": "https://ilostat.ilo.org (SDMX API)",
    "food": "https://www.fao.org/faostat/ (bulk downloads)",
}

# Wikidata items that have no ISO3 code (P298) but should be matched.
QID_TO_ISO3 = {"Q1246": "XKX", "Q865": "TWN", "Q219060": "PSE"}

NOW = dt.datetime.now(dt.timezone.utc)
TODAY = NOW.date().isoformat()


def log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def get_json(url: str, params: dict | None = None, timeout: int = 60, tries: int = 3, **kw):
    last = None
    for attempt in range(tries):
        try:
            r = SESSION.get(url, params=params, timeout=timeout, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def sparql(query: str, timeout: int = 90) -> list[dict]:
    data = get_json(
        "https://query.wikidata.org/sparql",
        params={"query": query, "format": "json"},
        headers={"Accept": "application/sparql-results+json"},
        timeout=timeout,
        tries=2,
    )
    rows = []
    for b in data["results"]["bindings"]:
        rows.append({k: v.get("value") for k, v in b.items()})
    return rows


def qid(uri: str | None) -> str | None:
    return uri.rsplit("/", 1)[-1] if uri else None


def is_qid_label(s: str | None) -> bool:
    """Wikidata returns the bare QID as label when no English label exists."""
    return not s or bool(re.fullmatch(r"Q\d+", s)) or s.startswith("http")


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
def flag_emoji(iso2: str | None) -> str | None:
    if not iso2 or len(iso2) != 2 or not iso2.isalpha():
        return None
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in iso2.upper())


def fetch_countries():
    """Country list (Wikidata sovereign states) + World Bank region names."""
    rows = sparql((QUERIES / "countries.sparql").read_text())
    out: dict[str, dict] = {}
    for r in rows:
        cq = qid(r.get("country"))
        iso3 = r.get("iso3") or QID_TO_ISO3.get(cq)
        if not iso3:
            continue
        c = out.setdefault(iso3, {"qid": cq, "iso2": r.get("iso2"), "name": r.get("countryLabel"),
                                  "capital": None, "continents": [], "currencies": []})
        if r.get("num") and not c.get("iso_num"):
            c["iso_num"] = r["num"].zfill(3)
        cap, cont = r.get("capitalLabel"), r.get("continentLabel")
        if cap and not is_qid_label(cap) and not c["capital"]:
            c["capital"] = cap
        if cont and not is_qid_label(cont) and cont not in c["continents"]:
            c["continents"].append(cont)
        code = r.get("curCode")
        if code and code not in [x["code"] for x in c["currencies"]]:
            c["currencies"].append({"code": code, "name": r.get("curLabel")})

    wb = get_json("https://api.worldbank.org/v2/country", params={"format": "json", "per_page": 400})
    for w in (wb[1] if isinstance(wb, list) and len(wb) > 1 else []):
        c = out.get(w.get("id"))
        if not c:
            continue
        region = (w.get("region") or {}).get("value", "").strip()
        if region and region != "Aggregates":
            c["region"] = region
        c["income_level"] = (w.get("incomeLevel") or {}).get("value", "").strip() or None
        lat, lon = as_float(w.get("latitude")), as_float(w.get("longitude"))
        if lat is not None and lon is not None:
            c["lat"], c["lon"] = lat, lon
        if not c["capital"] and w.get("capitalCity"):
            c["capital"] = w["capitalCity"]
        if not c.get("iso2") and w.get("iso2Code"):
            c["iso2"] = w["iso2Code"]
    for iso3, c in out.items():
        c["flag"] = flag_emoji(c.get("iso2"))
        if not c.get("region"):
            c["region"] = first(c["continents"])
    return out


# Main currency where Wikidata lists several still-valid ones and the rules can't decide.
MAIN_CURRENCY = {"ZWE": "ZWG"}
# Second currencies worth showing (legal tender alongside the local one, e.g. PAN, NAM, LSO).
CO_CIRCULATING = {"USD", "ZAR", "EUR", "INR"}


def pick_currencies(iso3: str, iso2: str | None, continents: list[str],
                    currencies: list[dict], rates: dict) -> list[dict]:
    """Drop obsolete codes (no live FX rate) and put the main currency first."""
    live = [c for c in currencies if c["code"] in rates or c["code"] == "USD"] or currencies
    if iso3 in MAIN_CURRENCY:
        main = MAIN_CURRENCY[iso3]
    elif len(live) == 1:
        main = live[0]["code"]
    else:
        codes = [c["code"] for c in live]
        prefix = [x for x in codes if iso2 and x[:2] == iso2]
        if len(prefix) == 1:
            main = prefix[0]
        elif "EUR" in codes and "Europe" in continents:
            main = "EUR"
        else:
            main = codes[0] if codes else None
    ordered = sorted(live, key=lambda c: c["code"] != main)
    return ordered[:1] + [c for c in ordered[1:] if c["code"] in CO_CIRCULATING]


WB_INDICATORS = {
    "population": "SP.POP.TOTL",
    "gdp_usd": "NY.GDP.MKTP.CD",
    "gdp_per_capita": "NY.GDP.PCAP.CD",
    "gdp_growth": "NY.GDP.MKTP.KD.ZG",
    "inflation": "FP.CPI.TOTL.ZG",
}


def fetch_worldbank():
    out: dict[str, dict] = {}
    for key, ind in WB_INDICATORS.items():
        data = get_json(
            f"https://api.worldbank.org/v2/country/all/indicator/{ind}",
            params={"format": "json", "mrnev": 1, "per_page": 1000},
        )
        rows = data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []
        for r in rows:
            iso3 = r.get("countryiso3code")
            if not iso3 or r.get("value") is None:
                continue
            out.setdefault(iso3, {})[key] = {"value": r["value"], "year": int(r["date"])}
    return out


def fetch_fx():
    data = get_json("https://open.er-api.com/v6/latest/USD")
    if data.get("result") != "success":
        raise RuntimeError(f"fx: {data.get('error-type')}")
    ts = data.get("time_last_update_unix")
    date = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat() if ts else TODAY
    return {"date": date, "rates": data["rates"]}


def fetch_politics():
    rows = sparql((QUERIES / "politics.sparql").read_text())
    agg: dict[str, dict] = {}
    for r in rows:
        cq = qid(r.get("country"))
        iso3 = r.get("iso3") or QID_TO_ISO3.get(cq)
        if not iso3:
            continue
        a = agg.setdefault(iso3, {"qid": cq})
        for key in ("govLabel", "hosLabel", "hogLabel", "legLabel", "hosOfficeLabel",
                    "hogOfficeLabel", "hosApptLabel", "hogApptLabel", "hosTerm", "hogTerm"):
            v = r.get(key)
            if v and not is_qid_label(v):
                lst = a.setdefault(key, [])
                if v not in lst:
                    lst.append(v)
    return agg


def _election_query(with_winner: bool) -> str:
    q = (QUERIES / "elections.sparql").read_text()
    start = (NOW.date() - dt.timedelta(days=730)).isoformat()
    end = (NOW.date() + dt.timedelta(days=365 * 5)).isoformat()
    q = q.replace("{START}", start).replace("{END}", end)
    if with_winner:
        return q.replace("{WINNER_START}", "").replace("{WINNER_END}", "")
    return re.sub(r"\{WINNER_START\}.*?\{WINNER_END\}", "", q)


def fetch_elections():
    try:
        rows = sparql(_election_query(True), timeout=90)
    except RuntimeError as e:
        log(f"  elections with winners failed ({e}); retrying without winners")
        rows = sparql(_election_query(False), timeout=90)
    out: dict[str, dict] = {}
    for r in rows:
        eq = qid(r.get("e"))
        e = out.setdefault(eq, {
            "qid": eq,
            "label": r.get("eLabel"),
            "date": r.get("d"),
            "precision": int(r.get("prec") or 9),
            "country_qid": qid(r.get("c")),
            "types": [],
            "winners": [],
        })
        t, w = r.get("tLabel"), r.get("wLabel")
        if t and not is_qid_label(t) and t not in e["types"]:
            e["types"].append(t)
        if w and not is_qid_label(w) and w not in e["winners"]:
            e["winners"].append(w)
    return list(out.values())


IPU_FIELDS = ["chamber_name", "statutory_members_number", "current_members_number",
              "electoral_system", "electoral_subsystem", "designation_mode",
              "parliamentary_term", "last_election", "struct_parl_status",
              "parliament", "is_suspended_chamber", "directly_elected_number",
              "min_age_vote_elect", "current_women_percent"]


def ipu_unwrap(v):
    """IPU values are nested: time series lists, {value, missing_reason}, {term}, {en, fr}."""
    for _ in range(6):
        if isinstance(v, list) and v and isinstance(v[0], dict) and "date_from" in v[0]:
            v = sorted(v, key=lambda x: x.get("date_from") or "")[-1].get("value")
        elif isinstance(v, dict) and "missing_reason" in v and "value" in v:
            v = v["value"]
        else:
            break
    if isinstance(v, dict) and "term" in v and len(v) <= 2:
        v = v["term"]
    elif isinstance(v, dict) and "en" in v:
        v = v["en"]
    return v


def fetch_ipu():
    out = []
    page = 1
    while True:
        data = get_json(
            "https://api.data.ipu.org/v1/chambers",
            params={"page[size]": 50, "page[number]": page},
            timeout=120,
        )
        for ch in data.get("data", []):
            a = ch.get("attributes", {})
            rec = {"id": ch.get("id")}
            for f in IPU_FIELDS:
                rec[f] = ipu_unwrap(a.get(f))
            out.append(rec)
        if not data.get("links", {}).get("next") or not data.get("data"):
            break
        page += 1
        if page > 50:
            break
    return out


FETCHERS = {
    "countries": fetch_countries,
    "worldbank": fetch_worldbank,
    "fx": fetch_fx,
    "politics": fetch_politics,
    "elections": fetch_elections,
    "ipu": fetch_ipu,
    "bis": lambda: monetary.fetch_bis(SESSION),
    "macro": lambda: monetary.fetch_macro(SESSION),
    "trade": lambda: trade.fetch_trade(SESSION, (load_cache("trade") or {}).get("data")),
    "tariffs": lambda: trade.fetch_tariffs(SESSION),
    "us_customs": lambda: trade.fetch_us_customs(SESSION, (load_cache("us_customs") or {}).get("data")),
    "services": lambda: trade.fetch_services(SESSION),
    "census": lambda: trade.fetch_census(SESSION),
    "labour": lambda: labour.fetch_labour(SESSION),
    "food": lambda: food.fetch_food(SESSION, (load_cache("food") or {}).get("data")),
}


# --------------------------------------------------------------------------- #
# Cache layer
# --------------------------------------------------------------------------- #
def load_cache(name: str):
    p = RAW / f"{name}.json"
    if p.exists():
        return json.loads(p.read_text())
    return None


def run_source(name: str, force: bool) -> tuple[object, dict]:
    cache = load_cache(name)
    status = {"url": SOURCE_URLS[name]}
    if cache and not force:
        age = NOW - dt.datetime.fromisoformat(cache["fetched_at"])
        if age < dt.timedelta(hours=MAX_AGE_HOURS[name]):
            log(f"- {name}: cache fresh ({age.total_seconds() / 3600:.1f}h old), skipping")
            return cache["data"], {**status, "status": "cached", "fetched_at": cache["fetched_at"]}
    log(f"- {name}: fetching...")
    t0 = time.time()
    try:
        data = FETCHERS[name]()
        if not data:
            raise RuntimeError("empty result")
        RAW.mkdir(parents=True, exist_ok=True)
        stamp = NOW.isoformat(timespec="seconds")
        (RAW / f"{name}.json").write_text(json.dumps({"fetched_at": stamp, "data": data},
                                                     ensure_ascii=False, separators=(",", ":")))
        log(f"  ok in {time.time() - t0:.1f}s")
        return data, {**status, "status": "ok", "fetched_at": stamp}
    except Exception as e:  # noqa: BLE001 - any failure falls back to cache
        log(f"  FAILED: {e}")
        if cache:
            return cache["data"], {**status, "status": "stale", "error": str(e)[:300],
                                   "fetched_at": cache["fetched_at"]}
        return None, {**status, "status": "error", "error": str(e)[:300]}


# --------------------------------------------------------------------------- #
# Normalisation helpers
# --------------------------------------------------------------------------- #
ACRONYM_FIX = {"Pr": "PR", "Fptp": "FPTP", "Trs": "TRS", "Stv": "STV", "Mmp": "MMP",
               "Sntv": "SNTV", "Av": "AV", "Bv": "BV", "Pbv": "PBV", "Lv": "LV"}


TERM_LABELS = {
    "proportional_representation": "Proportional representation",
    "plurality_majority": "Plurality / majority",
    "mixed_system": "Mixed system",
    "other_systems": "Other system",
    "list_proportional_representation_list_pr": "Party-list proportional representation",
    "first_past_the_post_fptp": "First past the post (single-member districts)",
    "parallel_systems": "Parallel system (part list PR, part districts)",
    "two_round_system_trs": "Two-round system",
    "mixed_member_proportional_system_mmp": "Mixed-member proportional (MMP)",
    "single_non_transferable_vote_sntv": "Single non-transferable vote (SNTV)",
    "block_vote_bv": "Block vote",
    "single_transferable_vote_stv": "Single transferable vote (STV)",
    "alternative_vote_av": "Alternative (ranked) vote",
    "first_past_the_post_fptp__block_vote_bv": "First past the post + block vote",
    "directly_elected": "Directly elected by voters",
    "indirectly_elected": "Indirectly elected (by other bodies)",
    "appointed": "Appointed",
    "lower_chamber": "Lower chamber",
    "upper_chamber": "Upper chamber",
}


def humanize(term):
    if not term or not isinstance(term, str):
        return None
    if term in TERM_LABELS:
        return TERM_LABELS[term]
    words = term.split("_")
    if len(words) > 1 and words[-1].title() in ACRONYM_FIX:
        acr = ACRONYM_FIX[words[-1].title()]
        body = " ".join(words[:-1])
        return f"{body[:1].upper()}{body[1:]} ({acr})"
    s = " ".join(words)
    return s[:1].upper() + s[1:]


MONARCH_WORDS = re.compile(r"monarch|king|queen|emir|sultan|emperor|grand duke|prince|"
                           r"co-prince|pope|yang di-pertuan", re.I)


def system_category(govs: list[str], hos_office: str | None = None,
                    same_person: bool = False, has_hog: bool = False) -> str:
    g = " | ".join(govs).lower()
    if "absolute monarchy" in g:
        return "Absolute monarchy"
    if "theocra" in g:
        return "Theocracy"
    if any(k in g for k in ("one-party", "single-party", "communist state", "communist dictatorship")):
        return "One-party state"
    if "military junta" in g or "provisional government" in g or "transitional" in g:
        return "Military / transitional"
    if "semi-presidential" in g:
        return "Semi-presidential"
    if "monarchy" in g:
        return "Constitutional monarchy"
    if "parliamentary" in g:
        return "Parliamentary republic"
    if "presidential" in g:
        return "Presidential republic"
    # Wikidata is vague ("federal republic") or empty: infer from the executive's shape.
    if hos_office and MONARCH_WORDS.search(hos_office):
        return "Constitutional monarchy"
    if same_person:
        return "Presidential republic"
    if has_hog:
        return "Parliamentary republic"
    return "Other / unknown"


def selection_text(appointers: list[str], office: str | None, govs: list[str], role: str) -> str | None:
    g = " ".join(govs).lower()
    if role == "hos" and "monarchy" in g and office and MONARCH_WORDS.search(office):
        return "Hereditary monarch"
    popular = [a for a in appointers if "election" in a.lower()]
    appointers = [a for a in appointers if a not in popular]
    if popular and not appointers:
        return "Popular election"
    if appointers:
        if any("electoral college" in a.lower() for a in appointers):
            return "Elected indirectly by " + ", ".join(appointers)
        return "Appointed or elected by " + ", ".join(appointers)
    return None


def fmt_date(iso: str | None, precision: int) -> str | None:
    if not iso:
        return None
    d = iso[:10]
    if precision >= 11:
        return d
    if precision == 10:
        return d[:7]
    return d[:4]


SKIP_ELECTION = re.compile(r"municipal|local|gubernatorial|state election|primary|leadership|"
                           r"by-election|regent|mayor|regional|provincial|mock|show election|"
                           r"county|city council|cantonal|party|m[aä]slihat", re.I)


def election_kind(label: str, types: list[str]) -> str:
    s = (label + " " + " ".join(types)).lower()
    if "referendum" in s or "plebiscite" in s:
        return "Referendum"
    if "presidential" in s:
        return "Presidential"
    if "european parliament" in s:
        return "European Parliament"
    if any(k in s for k in ("parliament", "legislative", "general", "federal", "national assembly",
                            "senate", "house of", "congress", "duma", "majlis", "assembly")):
        return "Legislative / general"
    if re.search(r"^\d{4} .+ elections$", label.strip()):
        return "Legislative / general"  # e.g. "2026 United States elections" (midterms)
    return "Other"


def election_status(types: list[str], date: str | None) -> str:
    """`date` is already cut to its precision (YYYY, YYYY-MM or YYYY-MM-DD)."""
    t = " ".join(types).lower()
    for s in ("cancelled", "annulled", "postponed"):
        if s in t:
            return s
    if not date:
        return "held"
    if len(date) == 10:
        return "upcoming" if date > TODAY else "held"
    # Year/month precision: the current year/month counts as upcoming.
    return "upcoming" if date >= TODAY[:len(date)] else "held"


def deep_merge(base: dict, extra: dict) -> dict:
    for k, v in extra.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def first(lst):
    return lst[0] if lst else None


def as_int(v):
    f = as_float(v)
    return int(f) if f is not None else None


def as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Merge
# --------------------------------------------------------------------------- #
def merge(src: dict) -> list[dict]:
    rc = src.get("countries") or {}
    wb = src.get("worldbank") or {}
    fx = src.get("fx") or {"rates": {}, "date": None}
    pol = src.get("politics") or {}
    els = src.get("elections") or []
    ipu = src.get("ipu") or []

    # Country universe: every current sovereign state in Wikidata.
    iso3s = set(rc)
    iso2_to_iso3 = {v["iso2"]: k for k, v in rc.items() if v.get("iso2")}
    qid_to_iso3 = {v["qid"]: k for k, v in list(rc.items()) + list(pol.items()) if v.get("qid")}

    # IPU chambers per country (parliament field holds ISO2)
    chambers: dict[str, list] = {}
    for ch in ipu:
        iso2 = ch.get("parliament") or (ch.get("id") or "")[:2]
        iso3 = iso2_to_iso3.get(iso2)
        if iso3:
            chambers.setdefault(iso3, []).append(ch)

    # Elections per country
    elections: dict[str, list] = {}
    for e in els:
        iso3 = qid_to_iso3.get(e.get("country_qid"))
        label = e.get("label") or ""
        if not iso3 or is_qid_label(label):
            continue
        if SKIP_ELECTION.search(label) or any(SKIP_ELECTION.search(t) for t in e["types"]
                                              if "general" not in t.lower()):
            continue
        date = fmt_date(e.get("date"), e.get("precision", 9))
        elections.setdefault(iso3, []).append({
            "name": label,
            "kind": election_kind(label, e["types"]),
            "date": date,
            "date_precision": {11: "day", 10: "month"}.get(e.get("precision"), "year"),
            "status": election_status(e["types"], date),
            "winners": e.get("winners") or [],
            "snap": any("snap" in t.lower() for t in e["types"]),
            "wikidata": f"https://www.wikidata.org/wiki/{e['qid']}",
        })

    overrides = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}

    countries = []
    for iso3 in sorted(iso3s):
        base = rc.get(iso3, {})
        w = wb.get(iso3, {})
        p = pol.get(iso3, {})
        govs = p.get("govLabel", [])

        currencies = []
        for c in pick_currencies(iso3, base.get("iso2"), base.get("continents", []),
                                 base.get("currencies", []), fx["rates"]):
            rate = fx["rates"].get(c["code"])
            currencies.append({**c, "per_usd": rate,
                               "usd_value": (1 / rate) if rate else None})

        chamber_list = []
        for ch in sorted(chambers.get(iso3, []), key=lambda c: c.get("id") or ""):
            last = ch.get("last_election")
            last_date = None
            if isinstance(last, dict):
                last_date = (last.get("to") or last.get("from") or "")[:10] or None
            elif isinstance(last, str):
                last_date = last[:10]
            term = as_float(ch.get("parliamentary_term"))
            next_est = None
            if last_date and term and ch.get("designation_mode") != "appointed":
                next_est = str(int(last_date[:4]) + int(round(term)))
            chamber_list.append({
                "name": ch.get("chamber_name"),
                "role": humanize(ch.get("struct_parl_status")),
                "seats": as_int(ch.get("statutory_members_number")) or as_int(ch.get("current_members_number")),
                "directly_elected": as_int(ch.get("directly_elected_number")),
                "how_chosen": humanize(ch.get("designation_mode")),
                "electoral_system": humanize(ch.get("electoral_system")),
                "electoral_subsystem": humanize(ch.get("electoral_subsystem")),
                "term_years": term,
                "last_election": last_date,
                "next_election_estimate": next_est,
                "women_percent": as_float(ch.get("current_women_percent")),
                "voting_age": as_int(ch.get("min_age_vote_elect")),
                "suspended": bool(ch.get("is_suspended_chamber")),
                "ipu": f"https://data.ipu.org/parliament/{(ch.get('id') or '')[:2]}",
            })

        el = sorted(elections.get(iso3, []), key=lambda e: e["date"] or "")
        upcoming = [e for e in el if e["status"] == "upcoming"]
        hos_office = first(p.get("hosOfficeLabel", []))
        hog_office = first(p.get("hogOfficeLabel", []))
        same = bool(p.get("hosLabel")) and p.get("hosLabel") == p.get("hogLabel")

        rec = {
            "iso3": iso3,
            "iso2": base.get("iso2"),
            "iso_num": base.get("iso_num"),
            "lat": base.get("lat"),
            "lon": base.get("lon"),
            "name": base.get("name") or iso3,
            "flag": base.get("flag"),
            "region": base.get("region"),
            "continent": ", ".join(base.get("continents", [])) or None,
            "income_level": base.get("income_level"),
            "capital": base.get("capital"),
            "economy": {
                k: (w.get(k) or {}).get("value") for k in WB_INDICATORS
            } | {
                f"{k}_year": (w.get(k) or {}).get("year") for k in WB_INDICATORS
            } | {
                "currencies": currencies,
                "fx_date": fx.get("date"),
            },
            "politics": {
                "system": govs,
                "system_category": system_category(govs, hos_office, same, bool(p.get("hogLabel"))),
                "head_of_state": {
                    "title": hos_office,
                    "name": ", ".join(p.get("hosLabel", [])) or None,
                    "selection": selection_text(p.get("hosApptLabel", []), hos_office, govs, "hos"),
                    "term_years": as_float(first(p.get("hosTerm", []))),
                },
                "head_of_government": {
                    "title": hog_office,
                    "name": ", ".join(p.get("hogLabel", [])) or None,
                    "selection": selection_text(p.get("hogApptLabel", []), hog_office, govs, "hog"),
                    "term_years": as_float(first(p.get("hogTerm", []))),
                },
                "same_person": same,
                "legislature": {
                    "name": ", ".join(p.get("legLabel", [])) or None,
                    "structure": {0: None, 1: "Unicameral", 2: "Bicameral"}.get(
                        len(chamber_list), f"{len(chamber_list)} chambers"),
                    "chambers": chamber_list,
                    "total_seats": sum(c["seats"] or 0 for c in chamber_list) or None,
                },
                "elections": el,
                "next_election": upcoming[0] if upcoming else None,
            },
            "wikidata": f"https://www.wikidata.org/wiki/{p['qid']}" if p.get("qid") else None,
        }
        if iso3 in overrides:
            deep_merge(rec, overrides[iso3])
        countries.append(rec)
    annotate_importance(countries)
    return countries


# --------------------------------------------------------------------------- #
# Election importance (formula) and world-perspective sentence (template)
# --------------------------------------------------------------------------- #
# How much each kind of election decides who really holds power, by system type.
# Values are 0-100: "how decisive is this vote for who governs the country".
POWER_SCORE = {
    #  system category              presidential  legislative  referendum
    "Presidential republic":        (92,          62,          55),
    "Semi-presidential":            (88,          72,          55),
    "Parliamentary republic":       (35,          92,          60),
    "Constitutional monarchy":      (0,           92,          60),
    "Semi-constitutional monarchy": (0,           45,          40),
    "Absolute monarchy":            (0,           20,          30),
    "Theocracy":                    (55,          40,          35),
    "One-party state":              (20,          22,          25),
    "Military / transitional":      (88,          80,          75),
    "Other / unknown":              (60,          60,          50),
}

WHAT_DECIDED = {
    ("Presidential", True): "voters choose the president, who also runs the government",
    ("Presidential", False): "voters choose the head of state",
    ("Legislative / general", True): "voters elect the legislature that checks the president",
    ("Legislative / general", False): "the vote decides which party or coalition forms the government",
    ("Referendum", True): "voters decide a question directly",
    ("Referendum", False): "voters decide a question directly",
}


def election_importance(kind: str, name: str, category: str, same_person: bool, snap: bool) -> int:
    pres, leg, ref = POWER_SCORE.get(category, POWER_SCORE["Other / unknown"])
    n = name.lower()
    if kind == "Presidential":
        score = pres or 30
    elif kind == "Legislative / general":
        score = leg
        # A "general election" in a presidential system usually elects the president too.
        if "general" in n and category in ("Presidential republic", "Semi-presidential"):
            score = max(score, pres)
    elif kind == "Referendum":
        score = ref
    elif kind == "European Parliament":
        score = 35
    else:
        score = 45
    if snap:
        score += 5  # snap elections usually follow a political crisis
    return max(5, min(99, int(score)))


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def world_note(c: dict, e: dict, gdp_rank: dict, pop_rank: dict, world_gdp: float, world_pop: float) -> str:
    econ = c["economy"]
    pol = c["politics"]
    cat = pol["system_category"]
    presidential = cat in ("Presidential republic", "Semi-presidential", "Military / transitional")
    kind = e["kind"]
    if kind == "Presidential" and not presidential and cat != "Theocracy":
        what = "voters (or parliament) choose a largely ceremonial president"
    elif cat == "Semi-constitutional monarchy" and kind != "Referendum":
        what = "the elected parliament shares power with a monarch who appoints the government"
    elif cat in ("One-party state", "Absolute monarchy"):
        what = "the vote happens under tightly controlled politics, so it signals stability more than change"
    else:
        what = WHAT_DECIDED.get((kind, presidential if kind != "Presidential" else pol["same_person"]),
                                "the vote shapes national politics")
    if e.get("snap"):
        what = "an early (snap) vote after political turmoil: " + what

    gdp, pop = econ.get("gdp_usd"), econ.get("population")
    g_rank, p_rank = gdp_rank.get(c["iso3"]), pop_rank.get(c["iso3"])
    g_share = 100 * gdp / world_gdp if gdp and world_gdp else None
    p_share = 100 * pop / world_pop if pop and world_pop else None
    region = c.get("region") or "its region"

    if g_rank and g_rank <= 10:
        nth = "" if g_rank == 1 else ordinal(g_rank) + "-"
        weight = (f"as the world's {nth}largest economy ({g_share:.1f}% of global GDP), "
                  f"the result can move markets, trade and alliances worldwide")
    elif g_rank and g_rank <= 25:
        weight = (f"it is a top-25 economy ({ordinal(g_rank)}, {g_share:.1f}% of global GDP), "
                  f"so investors and partners in {region} watch it closely")
    elif p_rank and p_rank <= 20:
        weight = (f"with {p_share:.1f}% of the world's population ({ordinal(p_rank)} most populous), "
                  f"its direction matters for {region} and global development")
    elif cat in ("Military / transitional",):
        weight = "a return to elected government would matter for regional security"
    elif g_share is not None:
        share = f"{g_share:.2f}%" if g_share >= 0.01 else "under 0.01%"
        weight = (f"its economy is small on a global scale ({share} of world GDP), "
                  f"so the impact is mainly within {region}")
    else:
        weight = f"the impact is mainly within {region}"
    s = f"{c['name']}: {what}; {weight}."
    return s[:1].upper() + s[1:]


def annotate_importance(countries: list[dict]) -> None:
    gdps = sorted(((c["economy"]["gdp_usd"] or 0, c["iso3"]) for c in countries), reverse=True)
    pops = sorted(((c["economy"]["population"] or 0, c["iso3"]) for c in countries), reverse=True)
    gdp_rank = {iso: i + 1 for i, (v, iso) in enumerate(gdps) if v}
    pop_rank = {iso: i + 1 for i, (v, iso) in enumerate(pops) if v}
    world_gdp = sum(v for v, _ in gdps)
    world_pop = sum(v for v, _ in pops)
    for c in countries:
        econ = c["economy"]
        econ["gdp_rank"] = gdp_rank.get(c["iso3"])
        econ["world_gdp_share"] = (round(100 * econ["gdp_usd"] / world_gdp, 3)
                                   if econ.get("gdp_usd") and world_gdp else None)
        econ["world_pop_share"] = (round(100 * econ["population"] / world_pop, 3)
                                   if econ.get("population") and world_pop else None)
        econ["ranked_countries"] = len(gdp_rank)
        pol = c["politics"]
        for e in pol["elections"]:
            if "importance" not in e:  # an override may set it by hand
                e["importance"] = election_importance(e["kind"], e["name"], pol["system_category"],
                                                      pol["same_person"], e.get("snap", False))
            if "world_note" not in e:
                e["world_note"] = world_note(c, e, gdp_rank, pop_rank, world_gdp, world_pop)


def coverage(countries: list[dict]) -> dict:
    checks = {
        "population": lambda c: c["economy"]["population"] is not None,
        "gdp_usd": lambda c: c["economy"]["gdp_usd"] is not None,
        "fx_rate": lambda c: any(x["per_usd"] for x in c["economy"]["currencies"]),
        "system": lambda c: bool(c["politics"]["system"]),
        "head_of_state": lambda c: bool(c["politics"]["head_of_state"]["name"]),
        "head_of_government": lambda c: bool(c["politics"]["head_of_government"]["name"]),
        "chambers_with_seats": lambda c: any(x["seats"] for x in c["politics"]["legislature"]["chambers"]),
        "any_election": lambda c: bool(c["politics"]["elections"]),
        "next_election_known": lambda c: c["politics"]["next_election"] is not None or any(
            x["next_election_estimate"] for x in c["politics"]["legislature"]["chambers"]),
    }
    n = len(countries) or 1
    return {k: round(100 * sum(1 for c in countries if f(c)) / n, 1) for k, f in checks.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="ignore cache ages, refetch everything")
    ap.add_argument("--only", help="comma-separated sources to (re)fetch, e.g. fx,worldbank")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None

    src, status = {}, {}
    for name in FETCHERS:
        force = args.force or (only is not None and name in only)
        src[name], status[name] = run_source(name, force)

    if not src.get("countries"):
        log("No country list available (countries source failed and no cache). Aborting.")
        return 1

    countries = merge(src)
    cov = coverage(countries)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "countries.json").write_text(json.dumps(countries, ensure_ascii=False, separators=(",", ":")))
    meta = {"generated_at": NOW.isoformat(timespec="seconds"), "count": len(countries),
            "sources": status, "coverage_percent": cov}
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    if src.get("bis"):
        banks = monetary.build_central_banks(src["bis"], countries, src.get("macro"), src.get("labour"))
        (OUT / "central_banks.json").write_text(json.dumps(banks, ensure_ascii=False, separators=(",", ":")))
        if src.get("macro"):
            (OUT / "energy.json").write_text(json.dumps(src["macro"]["energy"], separators=(",", ":")))
        missing = [b["short"] for b in banks if b["rate"] is None or b["cpi"] is None]
        log(f"Wrote {len(banks)} central banks" + (f" (missing data: {', '.join(missing)})" if missing else ""))

    if src.get("trade"):
        t = trade.build_trade(src["trade"], src.get("tariffs"), src.get("us_customs"), countries,
                              src.get("services"), src.get("census"))
        (OUT / "trade.json").write_text(json.dumps(t, ensure_ascii=False, separators=(",", ":")))
        log(f"Wrote trade for {len(t['economies'])} economies, {len(t['pairs'])} pairs, {len(t['insights'])} insights")

    if src.get("labour"):
        lab = labour.build_labour(src["labour"], countries)
        (OUT / "labour.json").write_text(json.dumps(lab, ensure_ascii=False, separators=(",", ":")))
        log(f"Wrote labour data for {len(lab['countries'])} countries")

    if src.get("food"):
        fd = food.build_food(src["food"], countries)
        details = fd.pop("details")
        (OUT / "food.json").write_text(json.dumps(fd, ensure_ascii=False, separators=(",", ":")))
        (OUT / "food").mkdir(exist_ok=True)
        for iso, d in details.items():
            (OUT / "food" / f"{iso}.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
        log(f"Wrote food data for {len(details)} countries")

    log(f"\nWrote {len(countries)} countries to {OUT / 'countries.json'}")
    log("Coverage (% of countries with field):")
    for k, v in cov.items():
        log(f"  {k:24s} {v:5.1f}%")
    bad = [k for k, s in status.items() if s["status"] in ("error", "stale")]
    if bad:
        log(f"Sources with problems: {', '.join(bad)} (see site/data/meta.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
