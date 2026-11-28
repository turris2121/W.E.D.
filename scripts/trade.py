"""Trade between the largest economies: what they sell each other, by sector,
plus their tariffs and taxes, and rule-based insights.

Sources (all free, no API key):
  UN Comtrade public preview API   goods trade by HS chapter and by partner (annual),
                                   US monthly imports (for the effective tariff rate)
  World Bank API                   average applied tariffs, trade taxes, tax revenue,
                                   trade % of GDP, services trade
  OECD SDMX                        combined statutory corporate income tax rate
  US Treasury Fiscal Data          monthly customs duties collected by the US

Comtrade's keyless preview returns at most 500 rows and one period per call and
is rate limited, so calls are throttled and the raw cache is reused.
Russia no longer reports to Comtrade: its figures are "mirror" data, i.e. what
the other economies here report buying from / selling to it.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import math
import os
import time

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
ECONOMIES = ["USA", "CHN", "DEU", "JPN", "IND", "GBR", "FRA", "ITA",
             "CAN", "BRA", "RUS", "KOR", "MEX", "AUS", "ESP",
             "NLD", "SAU", "VNM"]  # NLD: Europe's main port; SAU: energy; VNM: China+1 supply chains
NON_REPORTING = {"RUS", "VNM"}  # no recent Comtrade reports: mirror data (what partners report)
HIST_START = 2018                # trends start the year the US-China tariffs began
SCHEMA = 2                       # bump to force a re-download of cached reporters
EU27 = {"AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA", "DEU", "GRC",
        "HUN", "IRL", "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "POL", "PRT", "ROU", "SVK",
        "SVN", "ESP", "SWE"}

# With a free Comtrade API key (env COMTRADE_KEY) we use the full data API: 100k rows per call.
# Without one, the keyless preview: 500 rows per call and a small, IP-based quota.
COMTRADE_KEY = os.environ.get("COMTRADE_KEY", "").strip()
CT = ("https://comtradeapi.un.org/data/v1/get/C/{freq}/HS" if COMTRADE_KEY
      else "https://comtradeapi.un.org/public/v1/preview/C/{freq}/HS")
CT_MAX_ROWS = 100_000 if COMTRADE_KEY else 500
CT_REF = "https://comtradeapi.un.org/files/v1/app/reference/{name}.json"
WB = "https://api.worldbank.org/v2/country/{iso}/indicator/{ind}"
OECD_CIT = ("https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_TAX_CIT@DF_CIT,/"
            "{areas}.A.CIT........")
TREASURY = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/mts/mts_table_4"
BATIS = "https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_BATIS@DF_BATIS,/{key}"
CENSUS = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
CENSUS_KEY = os.environ.get("CENSUS_KEY", "").strip()

SERVICE_TYPES = {
    "SC": "Transport", "SD": "Travel & tourism", "SE": "Construction", "SF": "Insurance & pensions",
    "SG": "Financial services", "SH": "Royalties & licences (IP)", "SI": "Telecom, computer & IT",
    "SJ": "Other business services", "SK": "Culture & recreation", "SA": "Processing for others",
    "SB": "Maintenance & repair", "SL": "Government services",
}
# Census country names for the economies here (plus the EU aggregate and Taiwan).
CENSUS_NAMES = {"CHINA": "CHN", "MEXICO": "MEX", "CANADA": "CAN", "GERMANY": "DEU", "JAPAN": "JPN",
                "INDIA": "IND", "UNITED KINGDOM": "GBR", "FRANCE": "FRA", "ITALY": "ITA", "BRAZIL": "BRA",
                "RUSSIA": "RUS", "KOREA, SOUTH": "KOR", "SOUTH KOREA": "KOR", "AUSTRALIA": "AUS", "SPAIN": "ESP",
                "NETHERLANDS": "NLD", "SAUDI ARABIA": "SAU", "VIETNAM": "VNM", "TAIWAN": "TWN",
                "SWITZERLAND": "CHE", "IRELAND": "IRL", "THAILAND": "THA", "EUROPEAN UNION": "EU"}

TAX_INDICATORS = {
    "tariff_weighted": "TM.TAX.MRCH.WM.AR.ZS",      # applied, trade-weighted mean, all products
    "tariff_simple": "TM.TAX.MRCH.SM.AR.ZS",        # applied, simple mean
    "tariff_mfn_weighted": "TM.TAX.MRCH.WM.FN.ZS",  # most-favoured-nation, weighted
    "tariff_manufactured": "TM.TAX.MANF.WM.AR.ZS",
    "tariff_primary": "TM.TAX.TCOM.WM.AR.ZS",
    "trade_taxes_pct_revenue": "GC.TAX.INTT.RV.ZS",
    "tax_revenue_pct_gdp": "GC.TAX.TOTL.GD.ZS",
    "trade_pct_gdp": "NE.TRD.GNFS.ZS",
    "services_exports": "BX.GSR.NFSV.CD",
    "services_imports": "BM.GSR.NFSV.CD",
}

# HS chapter -> sector. Chapters not listed fall into "Other".
SECTORS = [
    ("Food & agriculture", range(1, 25)),
    ("Ores & minerals", range(25, 27)),
    ("Fuels & energy", [27]),
    ("Chemicals & pharma", range(28, 39)),
    ("Plastics & rubber", range(39, 41)),
    ("Leather, wood & paper", range(41, 50)),
    ("Textiles & clothing", range(50, 68)),
    ("Stone, glass & ceramics", range(68, 71)),
    ("Gold, gems & jewellery", [71]),
    ("Metals", range(72, 84)),
    ("Machinery & computers", [84]),
    ("Electronics & electrical", [85]),
    ("Vehicles & parts", [87]),
    ("Aircraft, ships & rail", [86, 88, 89]),
    ("Instruments & medical", range(90, 93)),
    ("Other manufactures", range(93, 98)),
]
OTHER = "Other / unclassified"
SHORT_NAMES = {"CHN": "China", "KOR": "South Korea", "RUS": "Russia", "GBR": "United Kingdom", "USA": "United States"}
CHAPTER_SECTOR = {ch: name for name, chs in SECTORS for ch in chs}
SECTOR_ORDER = [s for s, _ in SECTORS] + [OTHER]

HS_CHAPTERS = {
    1: "Live animals", 2: "Meat", 3: "Fish & seafood", 4: "Dairy, eggs & honey", 5: "Other animal products",
    6: "Plants & flowers", 7: "Vegetables", 8: "Fruit & nuts", 9: "Coffee, tea & spices", 10: "Cereals",
    11: "Milling products", 12: "Oilseeds (soybeans…)", 13: "Gums & resins", 14: "Vegetable plaiting materials",
    15: "Animal & vegetable fats/oils", 16: "Prepared meat & fish", 17: "Sugar & confectionery", 18: "Cocoa",
    19: "Cereal & bakery products", 20: "Prepared vegetables & fruit", 21: "Miscellaneous food",
    22: "Beverages & spirits", 23: "Food waste & animal feed", 24: "Tobacco", 25: "Salt, stone & cement",
    26: "Ores, slag & ash", 27: "Mineral fuels, oil & gas", 28: "Inorganic chemicals", 29: "Organic chemicals",
    30: "Pharmaceuticals", 31: "Fertilisers", 32: "Dyes, paints & inks", 33: "Perfumes & cosmetics",
    34: "Soaps & waxes", 35: "Proteins, glues & enzymes", 36: "Explosives", 37: "Photographic goods",
    38: "Misc. chemical products", 39: "Plastics", 40: "Rubber", 41: "Hides & leather", 42: "Leather goods & bags",
    43: "Furs", 44: "Wood", 45: "Cork", 46: "Basketwork", 47: "Wood pulp", 48: "Paper & paperboard",
    49: "Printed books & media", 50: "Silk", 51: "Wool", 52: "Cotton", 53: "Other vegetable fibres",
    54: "Synthetic filaments", 55: "Synthetic staple fibres", 56: "Wadding & ropes", 57: "Carpets",
    58: "Special woven fabrics", 59: "Coated textiles", 60: "Knitted fabrics", 61: "Knitted clothing",
    62: "Woven clothing", 63: "Other textile articles", 64: "Footwear", 65: "Headgear", 66: "Umbrellas",
    67: "Feathers & artificial flowers", 68: "Stone & plaster articles", 69: "Ceramics", 70: "Glass",
    71: "Gold, gems & jewellery", 72: "Iron & steel", 73: "Iron & steel articles", 74: "Copper",
    75: "Nickel", 76: "Aluminium", 78: "Lead", 79: "Zinc", 80: "Tin", 81: "Other base metals",
    82: "Tools & cutlery", 83: "Misc. metal articles", 84: "Machinery & computers",
    85: "Electrical machinery & electronics", 86: "Railway equipment", 87: "Vehicles & parts",
    88: "Aircraft & spacecraft", 89: "Ships & boats", 90: "Optical, medical & precision instruments",
    91: "Clocks & watches", 92: "Musical instruments", 93: "Arms & ammunition", 94: "Furniture & lighting",
    95: "Toys, games & sports", 96: "Misc. manufactured articles", 97: "Works of art & antiques",
    99: "Unclassified / confidential",
}

# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
_last_call = [0.0]
CT_INTERVAL = 1.3  # seconds between Comtrade calls (the preview API rate-limits bursts)


class QuotaExceeded(RuntimeError):
    """Comtrade's keyless preview has a quota; once hit, stop calling and keep what we have."""


REFRESH_DAYS = 30  # re-download an economy's annual data after this many days


def _get(session, url, params=None, timeout=90, tries=4, as_json=True, headers=None):
    last = None
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=timeout, headers=headers)
            if r.status_code == 403 and "quota" in r.text.lower():
                raise QuotaExceeded(f"{url}: quota exceeded")
            if r.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json() if as_json else r.text
        except QuotaExceeded:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def comtrade(session, freq: str, period: str, reporter: int, flow: str,
             cmd: str = "TOTAL", partners: list[int] | None = None) -> list[dict]:
    """One Comtrade preview call. Returns aggregate rows only (all transport modes, all customs procedures)."""
    wait = CT_INTERVAL - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    params = {"reporterCode": reporter, "period": period, "cmdCode": cmd, "flowCode": flow}
    if partners is not None:
        params["partnerCode"] = ",".join(map(str, partners))
    try:
        data = _get(session, CT.format(freq=freq), params=params,
                    headers={"Ocp-Apim-Subscription-Key": COMTRADE_KEY} if COMTRADE_KEY else None)
    finally:
        _last_call[0] = time.time()
    if data.get("error"):
        raise RuntimeError(f"Comtrade: {data['error']}")
    rows = data.get("data") or []
    if len(rows) >= CT_MAX_ROWS:
        raise RuntimeError(f"Comtrade result truncated at {CT_MAX_ROWS} rows ({params})")
    return [r for r in rows
            if r.get("motCode", 0) == 0 and r.get("partner2Code", 0) == 0
            and r.get("customsCode", "C00") == "C00" and r.get("primaryValue") is not None]


# --------------------------------------------------------------------------- #
# Fetchers (raw data, cached by fetch_all.run_source)
# --------------------------------------------------------------------------- #
def _reference(session):
    reps = _get(session, CT_REF.format(name="Reporters"))["results"]
    pars = _get(session, CT_REF.format(name="partnerAreas"))["results"]
    iso_to_code = {}
    for r in reps:
        iso = r.get("reporterCodeIsoAlpha3")
        if iso in ECONOMIES and not r.get("isGroup") and not r.get("entryExpiredDate"):
            iso_to_code[iso] = r["reporterCode"]
    partner_iso = {}
    for p in pars:
        iso = (p.get("PartnerCodeIsoAlpha3") or "").strip()
        if p.get("isGroup") or not iso or iso.startswith(("_", "X")) or len(iso) != 3:
            continue
        partner_iso[str(p["PartnerCode"])] = [iso, p.get("text")]
    partner_iso["490"] = ["TWN", "Taiwan (Other Asia, nes)"]  # Comtrade's label for Taiwan
    missing = [e for e in ECONOMIES if e not in iso_to_code]
    if missing:
        raise RuntimeError(f"Comtrade reference has no code for {missing}")
    return iso_to_code, partner_iso


def _by_chapter(rows) -> dict:
    out = {}
    for r in rows:
        if str(r["cmdCode"]).isdigit():
            out[str(int(r["cmdCode"]))] = round(r["primaryValue"])
    return out


def _by_partner(rows) -> dict:
    return {str(r["partnerCode"]): round(r["primaryValue"]) for r in rows if r["partnerCode"] != 0}


def fetch_trade(session, prev: dict | None = None) -> dict:
    """Annual goods trade for ECONOMIES (~10 Comtrade calls per economy).

    Resumable: economies already in `prev` (the last cache) that are younger than
    REFRESH_DAYS are kept as they are. If Comtrade's quota runs out, the economies
    fetched so far are returned with complete=False and the next run continues."""
    prev = prev or {}
    if prev.get("codes") and prev.get("partner_iso") and all(e in prev["codes"] for e in ECONOMIES):
        iso_to_code, partner_iso = prev["codes"], prev["partner_iso"]
    else:
        iso_to_code, partner_iso = _reference(session)
    this_year = dt.date.today().year
    today = dt.date.today()
    out = {"codes": iso_to_code, "partner_iso": partner_iso, "reporters": dict(prev.get("reporters") or {})}
    set_codes = [iso_to_code[e] for e in ECONOMIES]
    mirror_codes = [iso_to_code[e] for e in ECONOMIES if e in NON_REPORTING]

    def fresh(rec):
        if rec.get("v") != SCHEMA:
            return False
        try:
            return (today - dt.date.fromisoformat(rec.get("fetched", "1900-01-01"))).days < REFRESH_DAYS
        except ValueError:
            return False

    todo = [e for e in ECONOMIES if e not in NON_REPORTING and not (e in out["reporters"] and fresh(out["reporters"][e]))]
    try:
        for iso in todo:
            _fetch_reporter(session, out, iso, iso_to_code, set_codes, mirror_codes, this_year, today)
    except QuotaExceeded as e:
        print(f"    trade: {e}; keeping {len(out['reporters'])} economies, will resume next run", flush=True)
        if not out["reporters"]:
            raise
    out["complete"] = all(e in out["reporters"] for e in ECONOMIES if e not in NON_REPORTING)
    return out


def _hist(rows) -> dict:
    """{year: {partnerCode: value}}, partner "0" = world."""
    out = {}
    for r in rows:
        out.setdefault(str(r["period"]), {})[str(r["partnerCode"])] = round(r["primaryValue"])
    return out


def _fetch_reporter(session, out, iso, iso_to_code, set_codes, mirror_codes, this_year, today):
    code = iso_to_code[iso]
    # Latest year this economy has reported (annual data lags ~6-10 months).
    year = None
    for y in range(this_year - 1, this_year - 4, -1):
        if comtrade(session, "A", str(y), code, "X", partners=[0]):
            year = y
            break
    if year is None:
        raise RuntimeError(f"No recent Comtrade data for {iso}")
    others = [c for c in set_codes if c != code]
    rec = {"v": SCHEMA, "year": year, "fetched": today.isoformat()}
    rec["exports_by_chapter"] = _by_chapter(comtrade(session, "A", str(year), code, "X", "AG2", [0]))
    rec["imports_by_chapter"] = _by_chapter(comtrade(session, "A", str(year), code, "M", "AG2", [0]))
    # Totals by partner for every year since HIST_START (one call per flow with a key;
    # the keyless preview allows one period per call, so it only gets this year and last).
    years = list(range(HIST_START, year + 1)) if COMTRADE_KEY else [year - 1, year]
    for flow, key in (("X", "exports_hist"), ("M", "imports_hist")):
        h = {}
        for i in range(0, len(years), 12 if COMTRADE_KEY else 1):  # max 12 periods per call
            h.update(_hist(comtrade(session, "A", ",".join(map(str, years[i:i + 12])), code, flow)))
        rec[key] = h
    cur, prv = rec["exports_hist"].get(str(year), {}), rec["exports_hist"].get(str(year - 1), {})
    rec["exports_by_partner"] = {k: v for k, v in cur.items() if k != "0"}
    rec["exports_by_partner_prev"] = {k: v for k, v in prv.items() if k != "0"}
    cur, prv = rec["imports_hist"].get(str(year), {}), rec["imports_hist"].get(str(year - 1), {})
    rec["imports_by_partner"] = {k: v for k, v in cur.items() if k != "0"}
    rec["imports_by_partner_prev"] = {k: v for k, v in prv.items() if k != "0"}
    # What it sells to each of the other major economies, by HS chapter
    # (one call with a key; 4 partners per call on the 500-row preview).
    to = {}
    step = len(others) if COMTRADE_KEY else 4
    for i in range(0, len(others), step):
        for r in comtrade(session, "A", str(year), code, "X", "AG2", others[i:i + step]):
            if str(r["cmdCode"]).isdigit():
                to.setdefault(str(r["partnerCode"]), {})[str(int(r["cmdCode"]))] = round(r["primaryValue"])
    rec["exports_to_majors_by_chapter"] = to
    # Mirror data for non-reporting economies: what this economy buys from them, by chapter.
    mir = {}
    for r in comtrade(session, "A", str(year), code, "M", "AG2", [c for c in mirror_codes if c != code]):
        if str(r["cmdCode"]).isdigit():
            mir.setdefault(str(r["partnerCode"]), {})[str(int(r["cmdCode"]))] = round(r["primaryValue"])
    rec["imports_from_mirror_by_chapter"] = mir
    out["reporters"][iso] = rec
    print(f"    trade: {iso} {year} ok", flush=True)
    return out


def fetch_tariffs(session) -> dict:
    """Tariffs and taxes: World Bank indicators + OECD corporate tax rate."""
    isos = ";".join(ECONOMIES)
    wb = {}
    for key, ind in TAX_INDICATORS.items():
        data = _get(session, WB.format(iso=isos, ind=ind), params={"format": "json", "mrnev": 1, "per_page": 100})
        for r in (data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []):
            if r.get("value") is not None:
                wb.setdefault(r["countryiso3code"], {})[key] = {"value": r["value"], "year": int(r["date"])}
    cit = {}
    try:
        text = _get(session, OECD_CIT.format(areas="+".join(ECONOMIES)),
                    params={"startPeriod": dt.date.today().year - 4, "format": "csv"}, as_json=False)
        for row in csv.DictReader(io.StringIO(text)):
            # TARGETING=ST is the standard statutory rate (TA = targeted small-business rates).
            if row.get("TARGETING") != "ST" or not row.get("OBS_VALUE"):
                continue
            iso, year = row["REF_AREA"], int(row["TIME_PERIOD"])
            if iso not in cit or year > cit[iso]["year"]:
                cit[iso] = {"value": float(row["OBS_VALUE"]), "year": year}
    except Exception as e:  # noqa: BLE001 - corporate tax is optional
        print(f"    tariffs: OECD corporate tax unavailable ({e})", flush=True)
    if not wb:
        raise RuntimeError("World Bank returned no tariff/tax data")
    return {"wb": wb, "cit": cit}


def fetch_us_customs(session, prev: dict | None) -> dict:
    """US customs duties (Treasury, monthly) and US goods imports (Comtrade, monthly).
    Imports are fetched only for months missing from the previous cache, so a daily run makes few calls."""
    data = _get(session, TREASURY, params={
        "filter": "classification_desc:eq:Customs Duties,record_date:gte:2023-01-01",
        "fields": "record_date,current_month_gross_rcpt_amt,current_month_refund_amt",
        "sort": "record_date", "page[size]": 200})
    duties, refunds = {}, {}  # gross collections, and refunds paid back to importers
    for r in data.get("data", []):
        g, f = r.get("current_month_gross_rcpt_amt"), r.get("current_month_refund_amt")
        if g not in (None, "null"):
            duties[r["record_date"][:7]] = round(float(g))
            refunds[r["record_date"][:7]] = round(float(f)) if f not in (None, "null") else 0
    if not duties:
        raise RuntimeError("Treasury returned no customs duties")
    imports = dict((prev or {}).get("imports", {}))
    months = sorted(duties)[-30:]
    last = months[-1]
    y, m = int(last[:4]), int(last[5:])
    recent = {f"{y - (m - k <= 0)}-{(m - k - 1) % 12 + 1:02d}" for k in range(4)}  # re-check the latest months
    usa = 842
    for mo in months:
        if mo in imports and mo not in recent:
            continue
        try:
            rows = comtrade(session, "M", mo.replace("-", ""), usa, "M", partners=[0])
        except QuotaExceeded as e:
            print(f"    us_customs: {e}; keeping {len(imports)} months of imports", flush=True)
            break
        if rows:
            imports[mo] = round(rows[0]["primaryValue"])
    return {"duties": duties, "refunds": refunds, "imports": imports}


# --------------------------------------------------------------------------- #
# Build site/data/trade.json
# --------------------------------------------------------------------------- #
def _sectors(chapters: dict) -> dict:
    out = {}
    for ch, v in chapters.items():
        s = CHAPTER_SECTOR.get(int(ch), OTHER)
        out[s] = out.get(s, 0) + v
    return out


def _shares(d: dict, total: float, n: int | None = None, key="name") -> list[dict]:
    items = sorted(d.items(), key=lambda kv: -kv[1])
    if n:
        items = items[:n]
    return [{key: k, "value": v, "share": round(100 * v / total, 2) if total else None} for k, v in items]


def _hhi(values) -> float:
    tot = sum(values)
    return round(sum((v / tot * 100) ** 2 for v in values)) if tot else 0


def _pct(a, b):
    return round(100 * (a - b) / b, 1) if a is not None and b else None


def build_trade(raw: dict, tariffs: dict | None, customs: dict | None, countries: list[dict]) -> dict:
    by_iso = {c["iso3"]: c for c in countries}
    codes = raw["codes"]
    code_iso = {str(v): k for k, v in codes.items()}
    piso = raw["partner_iso"]
    reps = raw["reporters"]
    # Economies we can show: those fetched so far, plus mirror-only ones once any partner is in.
    ECON = [e for e in ECONOMIES if e in reps or (e in NON_REPORTING and reps)]

    def pname(code: str):
        iso = (piso.get(code) or [None])[0]
        c = by_iso.get(iso)
        name = SHORT_NAMES.get(iso) or (c["name"] if c else (piso.get(code) or [None, code])[1])
        return iso, name, (c or {}).get("flag")

    # ---- bilateral matrix among majors: exporter-reported; Russia's exports are the partner's imports
    matrix = {}  # matrix[a][b] = value of goods a exports to b
    flows_by_chapter = {}  # flows_by_chapter[a][b] = {chapter: value}
    for a in ECON:
        matrix[a], flows_by_chapter[a] = {}, {}
        for b in ECON:
            if a == b:
                continue
            if a in NON_REPORTING:
                if b in reps:
                    matrix[a][b] = reps[b]["imports_by_partner"].get(str(codes[a]))
                    flows_by_chapter[a][b] = reps[b].get("imports_from_mirror_by_chapter", {}).get(str(codes[a]), {})
            else:
                matrix[a][b] = reps[a]["exports_by_partner"].get(str(codes[b]))
                flows_by_chapter[a][b] = reps[a]["exports_to_majors_by_chapter"].get(str(codes[b]), {})

    # ---- per-economy records
    econ = []
    group_exports_by_sector = {}
    for iso in ECON:
        c = by_iso.get(iso, {})
        mirror = iso in NON_REPORTING
        if mirror:
            ex_ch, im_ch = {}, {}
            ex_p, im_p = {}, {}
            for b, r in reps.items():
                for ch, v in r.get("imports_from_mirror_by_chapter", {}).get(str(codes[iso]), {}).items():
                    ex_ch[ch] = ex_ch.get(ch, 0) + v
                for ch, v in r["exports_to_majors_by_chapter"].get(str(codes[iso]), {}).items():
                    im_ch[ch] = im_ch.get(ch, 0) + v
                ex_p[str(codes[b])] = r["imports_by_partner"].get(str(codes[iso]), 0)
                im_p[str(codes[b])] = r["exports_by_partner"].get(str(codes[iso]), 0)
            ex_prev = {str(codes[b]): r["imports_by_partner_prev"].get(str(codes[iso])) for b, r in reps.items()}
            im_prev = {str(codes[b]): r["exports_by_partner_prev"].get(str(codes[iso])) for b, r in reps.items()}
            year = max(r["year"] for r in reps.values())
        else:
            r = reps[iso]
            ex_ch, im_ch = r["exports_by_chapter"], r["imports_by_chapter"]
            ex_p, im_p = r["exports_by_partner"], r["imports_by_partner"]
            ex_prev, im_prev = r["exports_by_partner_prev"], r["imports_by_partner_prev"]
            year = r["year"]
        exports, imports = sum(ex_p.values()) if mirror else sum(ex_ch.values()), \
            sum(im_p.values()) if mirror else sum(im_ch.values())
        ex_s, im_s = _sectors(ex_ch), _sectors(im_ch)
        for s, v in ex_s.items():
            if not mirror:
                group_exports_by_sector[s] = group_exports_by_sector.get(s, 0) + v

        def partners(cur, prev, total):
            out = []
            for item in _shares(cur, total, 10, key="code"):
                p_iso, name, flag = pname(item["code"])
                out.append({"iso3": p_iso, "name": name, "flag": flag, "value": item["value"],
                            "share": item["share"], "change_pct": _pct(item["value"], prev.get(item["code"])),
                            "major": p_iso in ECON})
            return out

        exp_partners = partners(ex_p, ex_prev, exports)
        imp_partners = partners(im_p, im_prev, imports)

        def bloc_share(d, total):
            eu = sum(v for k, v in d.items() if (piso.get(k) or [None])[0] in EU27 and (piso.get(k) or [None])[0] != iso)
            us = d.get(str(codes["USA"]), 0) if iso != "USA" else 0
            cn = d.get(str(codes["CHN"]), 0) if iso != "CHN" else 0
            return {"USA": round(100 * us / total, 1) if total else None,
                    "CHN": round(100 * cn / total, 1) if total else None,
                    "EU": round(100 * eu / total, 1) if total else None}

        def products(ch, total):
            return [{"hs": k, "name": HS_CHAPTERS.get(int(k), "HS " + k), "sector": CHAPTER_SECTOR.get(int(k), OTHER),
                     "value": v, "share": round(100 * v / total, 2) if total else None}
                    for k, v in sorted(ch.items(), key=lambda kv: -kv[1])[:12]]

        tw = (tariffs or {}).get("wb", {}).get(iso, {})
        cit = (tariffs or {}).get("cit", {}).get(iso)
        econ.append({
            "iso3": iso, "name": SHORT_NAMES.get(iso, c.get("name", iso)), "flag": c.get("flag"), "year": year, "mirror": mirror,
            "gdp_usd": (c.get("economy") or {}).get("gdp_usd"),
            "exports": exports, "imports": imports, "balance": exports - imports,
            "exports_by_sector": [{"sector": s, "value": v, "share": round(100 * v / exports, 2) if exports else None}
                                  for s, v in sorted(ex_s.items(), key=lambda kv: -kv[1])],
            "imports_by_sector": [{"sector": s, "value": v, "share": round(100 * v / imports, 2) if imports else None}
                                  for s, v in sorted(im_s.items(), key=lambda kv: -kv[1])],
            "top_exports": products(ex_ch, exports if not mirror else sum(ex_ch.values())),
            "top_imports": products(im_ch, imports if not mirror else sum(im_ch.values())),
            "export_partners": exp_partners, "import_partners": imp_partners,
            "export_bloc_share": bloc_share(ex_p, exports), "import_bloc_share": bloc_share(im_p, imports),
            "export_concentration_hhi": _hhi(ex_s.values()),
            "exports_change_pct": _pct(sum(ex_p.values()), sum(v for v in ex_prev.values() if v)) if not mirror else None,
            "taxes": {k: tw.get(k) for k in TAX_INDICATORS} | {"corporate_tax": cit},
        })

    # ---- revealed comparative advantage (vs the group of reporting majors)
    g_total = sum(group_exports_by_sector.values())
    for e in econ:
        rca = {}
        for s in e["exports_by_sector"]:
            g = group_exports_by_sector.get(s["sector"])
            if g and s["share"] is not None:
                rca[s["sector"]] = round(s["share"] / (100 * g / g_total), 2)
        e["rca"] = rca

    # ---- pairs (both directions, by sector + top products)
    pairs = {}
    for i, a in enumerate(ECON):
        for b in ECON[i + 1:]:
            ab, ba = matrix[a].get(b), matrix[b].get(a)
            if not ab and not ba:
                continue

            def side(x, y):
                ch = flows_by_chapter[x].get(y, {})
                tot = sum(ch.values())
                return {"value": matrix[x].get(y), "sectors": _shares(_sectors(ch), tot, None, "sector"),
                        "products": [{"hs": k, "name": HS_CHAPTERS.get(int(k), k), "value": v,
                                      "share": round(100 * v / tot, 1) if tot else None}
                                     for k, v in sorted(ch.items(), key=lambda kv: -kv[1])[:6]]}

            def prev(x, y):
                if x in NON_REPORTING:
                    return reps.get(y, {}).get("imports_by_partner_prev", {}).get(str(codes[x]))
                return reps[x]["exports_by_partner_prev"].get(str(codes[y]))

            pairs[f"{a}-{b}"] = {"a": a, "b": b, "ab": side(a, b), "ba": side(b, a),
                                 "ab_change_pct": _pct(ab, prev(a, b)), "ba_change_pct": _pct(ba, prev(b, a)),
                                 "total": (ab or 0) + (ba or 0)}

    us = build_us_tariff(customs)
    group = {"sectors": _shares(group_exports_by_sector, g_total, None, "sector"), "exports": g_total}
    out = {"complete": bool(raw.get("complete")) and len(ECON) == len(ECONOMIES), "economies": econ, "matrix": matrix, "pairs": pairs, "us_tariff": us, "group": group,
           "sector_order": SECTOR_ORDER, "eu27": sorted(EU27)}
    out["insights"] = insights(out)
    return out


def build_us_tariff(customs: dict | None):
    if not customs:
        return None
    rows = []
    refunds = customs.get("refunds", {})
    for mo in sorted(customs["duties"]):
        d, imp = customs["duties"][mo], customs["imports"].get(mo)
        rows.append({"month": mo, "duties": d, "refunds": refunds.get(mo, 0), "imports": imp,
                     "rate": round(100 * d / imp, 2) if imp else None})
    with_rate = [r for r in rows if r["rate"] is not None]
    last12 = rows[-12:]
    prev12 = rows[-24:-12]
    return {"monthly": rows,
            "latest": with_rate[-1] if with_rate else None,
            "duties_12m": sum(r["duties"] for r in last12),
            "duties_prev_12m": sum(r["duties"] for r in prev12) if len(prev12) == 12 else None,
            "refunds_12m": sum(r["refunds"] for r in last12),
            "latest_duties_month": rows[-1]}


# --------------------------------------------------------------------------- #
# Insights: every sentence is derived from the numbers above by a fixed rule.
# --------------------------------------------------------------------------- #
def _money(v):
    if v is None:
        return "n/a"
    a = abs(v)
    s = f"${a / 1e12:.2f}T" if a >= 1e12 else f"${a / 1e9:.0f}B" if a >= 1e9 else f"${a / 1e6:.0f}M"
    return ("−" if v < 0 else "") + s


def _month(mo: str) -> str:
    return dt.date(int(mo[:4]), int(mo[5:7]), 1).strftime("%B %Y")


def insights(t: dict) -> list[dict]:
    E = {e["iso3"]: e for e in t["economies"]}
    nm = lambda iso: E[iso]["name"] if iso in E else iso  # noqa: E731
    out = []

    # 1. Biggest relationships
    top = sorted(t["pairs"].values(), key=lambda p: -p["total"])[:3]
    if top:
        out.append({"kind": "relationship", "title": "The biggest trade relationships",
                    "text": "; ".join(f"{nm(p['a'])}–{nm(p['b'])} {_money(p['total'])}" for p in top) +
                            ". Values are goods traded in both directions in a year.",
                    "link": f"pair/{top[0]['a']}-{top[0]['b']}"})

    # 2. Biggest bilateral imbalance
    imb = []
    for p in t["pairs"].values():
        ab, ba = p["ab"]["value"] or 0, p["ba"]["value"] or 0
        imb.append((abs(ab - ba), p, ab - ba))
    imb.sort(key=lambda x: -x[0])
    if imb:
        _, p, d = imb[0]
        win, lose = (p["a"], p["b"]) if d > 0 else (p["b"], p["a"])
        out.append({"kind": "balance", "title": "Most lopsided relationship",
                    "text": f"{nm(win)} sells {nm(lose)} {_money(abs(d))} more than it buys from it, the largest "
                            f"bilateral surplus among these economies.", "link": f"pair/{p['a']}-{p['b']}"})

    # 3. US vs China as top market
    first_us = [e for e in t["economies"] if e["export_partners"] and e["export_partners"][0]["iso3"] == "USA"]
    first_cn = [e for e in t["economies"] if e["export_partners"] and e["export_partners"][0]["iso3"] == "CHN"]
    def who(lst):
        return f"{len(lst)} ({', '.join(e['name'] for e in lst)})" if lst else "none"
    out.append({"kind": "dependence", "title": "Whose customer?",
                "text": f"Among these economies, the US is the #1 export market for {who(first_us)}; "
                        f"China is #1 for {who(first_cn)}."})

    # 4. Most dependent on a single customer
    dep = sorted((e for e in t["economies"] if e["export_partners"] and not e["mirror"]),
                 key=lambda e: -(e["export_partners"][0]["share"] or 0))
    if dep:
        e = dep[0]; p = e["export_partners"][0]
        out.append({"kind": "dependence", "title": "Most exposed to one customer",
                    "text": f"{e['name']} sends {p['share']:.0f}% of its goods exports to {p['name']}. "
                            f"A tariff from that one buyer hits a large part of its export economy.",
                    "link": f"country/{e['iso3']}"})

    # 5. Biggest shifts between majors (trade diversion)
    shifts = []
    for p in t["pairs"].values():
        for x, y, side, ch in ((p["a"], p["b"], "ab", p["ab_change_pct"]), (p["b"], p["a"], "ba", p["ba_change_pct"])):
            v = p[side]["value"]
            if ch is not None and v and v > 20e9:
                shifts.append((ch, x, y, v))
    if shifts:
        lo, hi = min(shifts), max(shifts)
        out.append({"kind": "shift", "title": "Biggest year-on-year shifts",
                    "text": f"{nm(lo[1])}'s exports to {nm(lo[2])} changed {lo[0]:+.0f}% (now {_money(lo[3])}), "
                            f"while {nm(hi[1])}'s exports to {nm(hi[2])} changed {hi[0]:+.0f}% "
                            f"(now {_money(hi[3])}). Flows above $20B only.",
                    "link": f"pair/{'-'.join(sorted([lo[1], lo[2]], key=ECONOMIES.index))}"})

    # 6. Concentration of exports by sector
    conc = sorted(t["economies"], key=lambda e: -e["export_concentration_hhi"])
    if conc:
        hi_e, lo_e = conc[0], conc[-1]
        s = hi_e["exports_by_sector"][0]
        out.append({"kind": "structure", "title": "Least and most diversified exporters",
                    "text": f"{hi_e['name']} is the most concentrated: {s['sector'].lower()} is {s['share']:.0f}% of its "
                            f"exports{' (mirror data)' if hi_e['mirror'] else ''}. {lo_e['name']} is the most diversified.",
                    "link": f"country/{hi_e['iso3']}"})

    # 7. Specialisation (RCA)
    spec = []
    for e in t["economies"]:
        if e["mirror"] or not e["rca"]:
            continue
        cand = [(v, s) for s, v in e["rca"].items()
                if s != OTHER and any(x["sector"] == s and (x["share"] or 0) >= 5 for x in e["exports_by_sector"])]
        if cand:
            v, s = max(cand)
            spec.append(f"{e['name']}: {s.lower()} ({v:.1f}×)")
    if spec:
        out.append({"kind": "structure", "title": "What each economy specialises in",
                    "text": "Sector with the highest share of exports relative to the group average (only sectors ≥5% "
                            "of its exports): " + "; ".join(spec[:8]) + "."})

    # 8. Group sector mix
    g = t["group"]["sectors"]
    if g:
        out.append({"kind": "structure", "title": "What the big economies sell most",
                    "text": f"Across the economies that report, {g[0]['sector'].lower()} ({g[0]['share']:.0f}%), "
                            f"{g[1]['sector'].lower()} ({g[1]['share']:.0f}%) and {g[2]['sector'].lower()} "
                            f"({g[2]['share']:.0f}%) are the largest export sectors."})

    # 9. Surpluses / deficits
    bal = sorted((e for e in t["economies"] if not e["mirror"]), key=lambda e: e["balance"])
    if bal:
        out.append({"kind": "balance", "title": "Surplus and deficit champions",
                    "text": f"Largest goods surplus: {bal[-1]['name']} ({_money(bal[-1]['balance'])}). "
                            f"Largest deficit: {bal[0]['name']} ({_money(bal[0]['balance'])})."})

    # 10. Tariffs
    us = t.get("us_tariff")
    if us and us.get("latest"):
        l = us["latest"]
        base = next((r for r in us["monthly"] if r["month"] == "2024-12" and r["rate"]), None)
        txt = f"US customs duties collected were {l['rate']:.1f}% of goods imports in {_month(l['month'])}"
        if base:
            txt += f", up from {base['rate']:.1f}% in December 2024" if l["rate"] > base["rate"] else \
                   f", versus {base['rate']:.1f}% in December 2024"
        if us.get("duties_prev_12m"):
            txt += f". Duties collected in the last 12 months: {_money(us['duties_12m'])} " \
                   f"({_pct(us['duties_12m'], us['duties_prev_12m']):+.0f}% on the year before)"
        if us.get("refunds_12m", 0) > 0.1 * us["duties_12m"]:
            big = max(us["monthly"][-12:], key=lambda r: r["refunds"])
            txt += f". Refunds to importers were unusually large: {_money(us['refunds_12m'])} in the last 12 months, " \
                   f"peaking at {_money(big['refunds'])} in {_month(big['month'])}"
        out.append({"kind": "tariff", "title": "The US effective tariff rate", "text": txt + ".", "link": "us-tariff"})
    tw = [(e["taxes"]["tariff_weighted"]["value"], e) for e in t["economies"] if e["taxes"].get("tariff_weighted")]
    if tw:
        tw.sort(key=lambda x: x[0])
        out.append({"kind": "tariff", "title": "Highest and lowest scheduled tariffs",
                    "text": f"By the latest World Bank averages (trade-weighted, applied), {tw[-1][1]['name']} charges the most "
                            f"({tw[-1][0]:.1f}%) and {tw[0][1]['name']} the least ({tw[0][0]:.1f}%). These averages "
                            f"pre-date the 2025–26 tariff changes."})
    tt = [(e["taxes"]["trade_taxes_pct_revenue"]["value"], e) for e in t["economies"] if e["taxes"].get("trade_taxes_pct_revenue")]
    if tt:
        e = max(tt, key=lambda x: x[0])
        out.append({"kind": "tax", "title": "Who relies on trade taxes",
                    "text": f"Taxes on international trade are {e[0]:.1f}% of {e[1]['name']}'s government revenue, the highest "
                            f"here; the median is {sorted(x[0] for x in tt)[len(tt) // 2]:.1f}%."})
    return out
