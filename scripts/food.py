"""Food tab: what each country eats, how much it produces itself, its surpluses and shortfalls,
and which countries it buys food from.

Source: FAOSTAT bulk downloads (free, no key), https://www.fao.org/faostat/
  Food Balance Sheets (FBS): food supply (kcal, protein, fat per person per day), production,
      imports, exports, domestic supply per food, and FAO's import dependency / export ratios.
  Detailed Trade Matrix (TM): bilateral import values by product and partner.
The trade matrix is 420 MB zipped (8.5 GB of CSV); it is streamed, never unzipped to disk, and only
re-downloaded when FAO publishes a new version (checked with the Last-Modified header).
"""
from __future__ import annotations

import csv
import io
import re
import tempfile
import zipfile
from collections import defaultdict

BULK = "https://bulks-faostat.fao.org/production/"
FBS_FILE = "FoodBalanceSheets_E_All_Data.zip"
TM_FILE = "Trade_DetailedTradeMatrix_E_All_Data_(Normalized).zip"

# FBS elements kept (code -> short key)
FBS_ELEMENTS = {"5511": "prod", "5611": "imp", "5911": "exp", "5301": "supply", "5142": "food",
                "645": "kg", "664": "kcal", "674": "protein", "684": "fat", "501": "import_dep", "502": "export_ratio"}

# Display groups. FBS aggregate codes feeding each group's calories, and FAO's group code for ratios.
GROUPS = {
    "Cereals":                      {"kcal": ["2905"], "ratio": "2905"},
    "Roots & tubers":               {"kcal": ["2907"], "ratio": None},
    "Sugar & sweeteners":           {"kcal": ["2909"], "ratio": "2909"},
    "Pulses":                       {"kcal": ["2911"], "ratio": "2911"},
    "Fruits, vegetables & nuts":    {"kcal": ["2918", "2919", "2912"], "ratio": "2918"},
    "Oilseeds & oils":              {"kcal": ["2913", "2914"], "ratio": "2914"},
    "Meat":                         {"kcal": ["2943", "2945", "2946"], "ratio": "2943"},
    "Dairy & eggs":                 {"kcal": ["2948", "2949"], "ratio": "2948"},
    "Fish & seafood":               {"kcal": ["2960", "2961"], "ratio": "2960"},
    "Coffee, tea, cocoa & spices":  {"kcal": ["2922", "2923"], "ratio": None},
    "Beverages":                    {"kcal": ["2924"], "ratio": None},
    "Other":                        {"kcal": ["2928"], "ratio": None},
}
# FAO ratio rows for fruits and vegetables are separate; show both under one group.
RATIO_EXTRA = {"Fruits, vegetables & nuts": ["2918", "2919"], "Oilseeds & oils": ["2913", "2914"]}

# FBS leaf items -> display group (by name keywords; names use ',' or ';').
FBS_GROUP_RULES = [
    (r"wheat|rice|barley|maize and|^rye|oats|millet|sorghum|cereals", "Cereals"),
    (r"potato|cassava|sweet potatoes|yams|roots", "Roots & tubers"),
    (r"sugar|sweeteners|honey", "Sugar & sweeteners"),
    (r"^beans|^peas|pulses", "Pulses"),
    (r"oil|soyabeans|groundnuts|sunflower seed|rape and mustardseed|cottonseed|coconuts|sesame|palm kernels|olives|oilcrops", "Oilseeds & oils"),
    (r"apples|bananas|plantains|citrus|oranges|lemons|grapefruit|grapes|pineapples|dates|fruits|tomatoes|onions|vegetables|nuts", "Fruits, vegetables & nuts"),
    (r"bovine|mutton|pigmeat|poultry|meat, other|meat; other|offals|fats, animals|fats; animals", "Meat"),
    (r"milk|butter|cream|eggs", "Dairy & eggs"),
    (r"fish|crustaceans|cephalopods|molluscs|aquatic", "Fish & seafood"),
    (r"coffee|cocoa|tea|pepper|pimento|cloves|spices", "Coffee, tea, cocoa & spices"),
    (r"wine|beer|beverages|alcohol", "Beverages"),
]

# Trade matrix product (CPC code) -> display group; None = not food (feed, tobacco, fibres, live animals...)
CPC_GROUPS = [
    (("011", "231", "234", "237"), "Cereals"),
    (("012", "013", "213", "214"), "Fruits, vegetables & nuts"),
    (("014", "216", "217"), "Oilseeds & oils"),
    (("015",), "Roots & tubers"),
    (("017",), "Pulses"),
    (("018", "235", "232"), "Sugar & sweeteners"),
    (("016", "236"), "Coffee, tea, cocoa & spices"),
    (("211", "215"), "Meat"),
    (("022", "023", "221", "222"), "Dairy & eggs"),
    (("241", "242", "243", "244"), "Beverages"),
]
NOT_FOOD = ("019", "021", "029", "032", "218", "219", "233", "250", "261", "341", "345", "354", "391", "392")
F_RULES = [(r"meat|beef|pig|poultry|chicken|bacon|ham|sausage", "Meat"), (r"milk|cheese|yoghurt|whey|butter|egg", "Dairy & eggs"),
           (r"bread|pastry|cereal|pasta|biscuit|flour", "Cereals"), (r"chocolate|cocoa|coffee|tea", "Coffee, tea, cocoa & spices"),
           (r"juice|fruit|vegetable|nut", "Fruits, vegetables & nuts"), (r"oil|fat|margarine", "Oilseeds & oils"),
           (r"cotton|wool|hide|skin|waste|feed|tobacco", None)]


def tm_group(cpc: str, item: str):
    cpc = cpc.lstrip("'")
    if cpc.startswith("F"):
        for pat, g in F_RULES:
            if re.search(pat, item, re.I):
                return g
        return "Other"
    if cpc.startswith(NOT_FOOD):
        return None
    if cpc.startswith("239"):
        return "Dairy & eggs" if re.search(r"egg", item, re.I) else "Coffee, tea, cocoa & spices" if re.search(
            r"coffee|tea|mate", item, re.I) else "Other"
    for prefixes, g in CPC_GROUPS:
        if cpc.startswith(prefixes):
            return g
    return "Other"


def fbs_group(name: str) -> str:
    n = name.lower()
    for pat, g in FBS_GROUP_RULES:
        if re.search(pat, n):
            return g
    return "Other"


PRODUCT_KEYS = [("wheat", "wheat"), ("maize", "maize"), ("rice", "rice"), ("barley", "barley"), ("sorghum", "sorghum"),
                ("soyabean oil", "soya bean oil"), ("soyabeans", "soya beans"), ("palm oil", "palm oil"),
                ("sunflowerseed oil", "sunflower"), ("rape and mustard oil", "rapeseed"), ("groundnut", "groundnut"),
                ("olive oil", "olive oil"), ("bovine", "cattle"), ("poultry", "chicken"), ("pigmeat", "pig"),
                ("mutton", "sheep"), ("sugar (raw", "sugar"), ("bananas", "bananas"), ("apples", "apples"),
                ("potatoes", "potatoes"), ("coffee", "coffee"), ("cocoa", "cocoa"), ("tea", "tea"), ("beans", "beans"),
                ("cassava", "cassava"), ("onions", "onions"), ("tomatoes", "tomatoes"), ("oats", "oats")]


def _product_key(fbs_item: str) -> str | None:
    n = fbs_item.lower()
    for k, v in PRODUCT_KEYS:
        if n.startswith(k) or f" {k}" in n:
            return v
    return None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _download(session, name: str) -> tempfile.NamedTemporaryFile:
    tmp = tempfile.NamedTemporaryFile(suffix=".zip")
    with session.get(BULK + name, stream=True, timeout=600) as r:
        r.raise_for_status()
        for chunk in r.iter_content(1 << 20):
            tmp.write(chunk)
    tmp.flush()
    return tmp


def _last_modified(session, name: str) -> str | None:
    r = session.head(BULK + name, timeout=60)
    return r.headers.get("Last-Modified") if r.ok else None


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #
def _fetch_fbs(session) -> dict:
    tmp = _download(session, FBS_FILE)
    z = zipfile.ZipFile(tmp.name)
    name = [n for n in z.namelist() if n.endswith("All_Data.csv")][0]
    rows = csv.reader(io.TextIOWrapper(z.open(name), encoding="latin-1", newline=""))
    h = next(rows)
    ix = {k: i for i, k in enumerate(h)}
    years = sorted(int(c[1:]) for c in h if re.fullmatch(r"Y\d{4}", c))
    data: dict[str, dict] = {}
    names: dict[str, str] = {}
    trend: dict[str, dict] = defaultdict(dict)
    buf = [row for row in rows if row[ix["Element Code"]] in FBS_ELEMENTS]
    # latest year with calorie data (FAO adds year columns before filling them)
    latest = next(y for y in reversed(years)
                  if sum(1 for r in buf if r[ix["Element Code"]] == "664" and r[ix["Item Code"]] == "2901"
                         and r[ix[f"Y{y}"]]) > 100)
    col = ix[f"Y{latest}"]
    for row in buf:
        m49 = row[ix["Area Code (M49)"]].lstrip("'")
        item, el = row[ix["Item Code"]], FBS_ELEMENTS[row[ix["Element Code"]]]
        names[item] = row[ix["Item"]]
        v = _num(row[col])
        if v is not None:
            data.setdefault(m49, {}).setdefault(item, {})[el] = round(v, 3)
        if item == "2901" and el == "kcal":
            for y in years:
                t = _num(row[ix[f"Y{y}"]])
                if t is not None:
                    trend[m49][str(y)] = round(t)
    return {"year": latest, "data": data, "items": names, "kcal_trend": dict(trend)}


def _fetch_tm(session) -> dict:
    tmp = _download(session, TM_FILE)
    z = zipfile.ZipFile(tmp.name)
    name = [n for n in z.namelist() if "All_Data" in n][0]
    rows = csv.reader(io.TextIOWrapper(z.open(name), encoding="latin-1", newline=""))
    h = next(rows)
    ix = {k: i for i, k in enumerate(h)}
    E, Y, V = ix["Element Code"], ix["Year"], ix["Value"]
    R, P, C, I = ix["Reporter Country Code (M49)"], ix["Partner Country Code (M49)"], ix["Item Code (CPC)"], ix["Item"]
    group_cache: dict[tuple, str | None] = {}
    by_year: dict[str, dict] = {}
    partners: dict[str, str] = {}
    max_year = 0
    for row in rows:
        if row[E] != "5622":  # import value, 1000 US$
            continue
        y = int(row[Y])
        if y < max_year - 1:
            continue
        if y > max_year:
            max_year = y
            by_year = {k: v for k, v in by_year.items() if int(k) >= y - 1}
        key = (row[C], row[I])
        g = group_cache.get(key, "?")
        if g == "?":
            g = group_cache[key] = tm_group(*key)
        if g is None:
            continue
        v = _num(row[V])
        if not v:
            continue
        rep, par = row[R].lstrip("'"), row[P].lstrip("'")
        partners[par] = row[ix["Partner Countries"]]
        yr = by_year.setdefault(str(y), {}).setdefault(rep, {"groups": defaultdict(lambda: defaultdict(float)),
                                                             "items": defaultdict(lambda: defaultdict(float))})
        yr["groups"][g][par] += v
        yr["items"][row[I]][par] += v
    # Per reporter: latest year it reported, pruned to the biggest partners and products.
    out = {}
    for y in sorted(by_year, reverse=True):
        for rep, d in by_year[y].items():
            if rep in out:
                continue
            groups = {}
            for g, ps in d["groups"].items():
                top = sorted(ps.items(), key=lambda kv: -kv[1])
                groups[g] = {"total": round(sum(ps.values())), "partners": [[p, round(v)] for p, v in top[:10]]}
            items = sorted(d["items"].items(), key=lambda kv: -sum(kv[1].values()))[:30]
            out[rep] = {"year": int(y), "groups": groups,
                        "items": [{"item": it, "total": round(sum(ps.values())),
                                   "partners": [[p, round(v)] for p, v in sorted(ps.items(), key=lambda kv: -kv[1])[:6]]}
                                  for it, ps in items]}
    return {"year": max_year, "data": out, "partners": partners}


def fetch_food(session, prev: dict | None = None) -> dict:
    prev = prev or {}
    out = {"meta": {}}
    for key, fname, fn in (("fbs", FBS_FILE, _fetch_fbs), ("tm", TM_FILE, _fetch_tm)):
        lm = _last_modified(session, fname)
        if prev.get(key) and lm and prev.get("meta", {}).get(key) == lm:
            out[key] = prev[key]  # FAO has not published a new file
        else:
            out[key] = fn(session)
        out["meta"][key] = lm
    if not out["fbs"].get("data"):
        raise RuntimeError("FAOSTAT food balance sheets empty")
    return out


# --------------------------------------------------------------------------- #
# Build per-country view
# --------------------------------------------------------------------------- #
def build_food(raw: dict, countries: list[dict]) -> dict:
    fbs, tm = raw["fbs"], raw.get("tm") or {}
    names = fbs["items"]
    by_num = {c["iso_num"]: c for c in countries if c.get("iso_num")}
    partner_iso = {num: c["iso3"] for num, c in by_num.items()}
    partner_names = tm.get("partners", {})
    out = []
    for m49, items in fbs["data"].items():
        c = by_num.get(m49.zfill(3))
        if not c or "2901" not in items or items["2901"].get("kcal") is None:
            continue
        total = items["2901"]
        kcal = total["kcal"]
        animal = (items.get("2941") or {}).get("kcal")
        # calories by display group
        groups = []
        for g, spec in GROUPS.items():
            k = sum((items.get(code) or {}).get("kcal") or 0 for code in spec["kcal"])
            ratio_codes = RATIO_EXTRA.get(g, [spec["ratio"]] if spec["ratio"] else [])
            deps = [(items.get(rc) or {}).get("import_dep") for rc in ratio_codes]
            exps = [(items.get(rc) or {}).get("export_ratio") for rc in ratio_codes]
            deps = [d for d in deps if d is not None]
            exps = [e for e in exps if e is not None]
            groups.append({"group": g, "kcal": round(k), "share": round(100 * k / kcal, 1) if kcal else None,
                           "import_dependency": round(sum(deps) / len(deps), 1) if deps else None,
                           "export_ratio": round(sum(exps) / len(exps), 1) if exps else None})
        # individual foods
        foods = []
        for code, el in items.items():
            if code.startswith("29") or code == "2501":  # aggregates / population
                continue
            nm = names.get(code, code).replace(";", ",")
            prod, imp, exp, sup = el.get("prod"), el.get("imp"), el.get("exp"), el.get("supply")
            if not any(v for v in (el.get("kcal"), prod, imp, exp)):
                continue
            foods.append({
                "item": nm, "group": fbs_group(nm), "kcal": round(el.get("kcal") or 0, 1),
                "kg": round(el.get("kg") or 0, 1), "prod": prod, "imp": imp, "exp": exp, "supply": sup,
                "self_sufficiency": round(100 * prod / sup, 1) if prod is not None and sup and sup > 0 else None,
                "net_trade": round((exp or 0) - (imp or 0), 1),
            })
        top_foods = sorted([f for f in foods if f["kcal"] > 0], key=lambda f: -f["kcal"])[:12]
        t_raw = (tm.get("data") or {}).get(m49) or (tm.get("data") or {}).get(m49.zfill(3))
        shortfalls = sorted([f for f in foods if f["net_trade"] < 0], key=lambda f: f["net_trade"])[:10]
        surpluses = sorted([f for f in foods if f["net_trade"] > 0], key=lambda f: -f["net_trade"])[:10]

        # Suppliers for each shortfall: the matching traded product if there is one, else the food group.
        def suppliers_for(f):
            if not t_raw or f["group"] == "Fish & seafood":
                return None
            key = _product_key(f["item"])
            if key:
                cands = [it for it in t_raw["items"] if key in it["item"].lower()]
                if cands:
                    best = max(cands, key=lambda it: it["total"])
                    tot = sum(it["total"] for it in cands)
                    return {"basis": best["item"].replace(";", ","), "partners": [
                        {"name": partner_names.get(p, p).replace(";", ","), "iso3": partner_iso.get(p.zfill(3)),
                         "share": round(100 * v / best["total"], 1) if best["total"] else None} for p, v in best["partners"][:3]]}
            g = t_raw["groups"].get(f["group"])
            if not g:
                return None
            return {"basis": f["group"], "partners": [
                {"name": partner_names.get(p, p).replace(";", ","), "iso3": partner_iso.get(p.zfill(3)),
                 "share": round(100 * v / g["total"], 1) if g["total"] else None} for p, v in g["partners"][:3]]}
        for f in shortfalls:
            f["suppliers"] = suppliers_for(f)

        # trade partners
        t = t_raw
        partners = None
        if t:
            tot = defaultdict(float)
            for g in t["groups"].values():
                for p, v in g["partners"]:
                    tot[p] += v
            all_total = sum(g["total"] for g in t["groups"].values())

            def pinfo(p, v, base):
                return {"m49": p, "iso3": partner_iso.get(p.zfill(3)), "name": partner_names.get(p, p).replace(";", ","),
                        "value": v, "share": round(100 * v / base, 1) if base else None}
            partners = {
                "year": t["year"], "total_kusd": all_total,
                "top": [pinfo(p, round(v), all_total) for p, v in sorted(tot.items(), key=lambda kv: -kv[1])[:10]],
                "groups": {g: {"total": d["total"], "partners": [pinfo(p, v, d["total"]) for p, v in d["partners"]]}
                           for g, d in sorted(t["groups"].items(), key=lambda kv: -kv[1]["total"])},
                "items": [{"item": it["item"].replace(";", ","), "total": it["total"],
                           "partners": [pinfo(p, v, it["total"]) for p, v in it["partners"]]} for it in t["items"][:15]],
            }
        trend = fbs.get("kcal_trend", {}).get(m49, {})
        y10 = str(fbs["year"] - 10)
        out.append({
            "iso3": c["iso3"], "name": c["name"], "flag": c.get("flag"), "region": c.get("region"),
            "gdp_rank": c["economy"].get("gdp_rank"), "population": c["economy"].get("population"),
            "kcal": round(kcal), "protein": total.get("protein"), "fat": total.get("fat"),
            "animal_share": round(100 * animal / kcal, 1) if animal and kcal else None,
            "kcal_10y_ago": trend.get(y10), "kcal_trend": sorted([int(y), v] for y, v in trend.items()),
            "groups": groups, "top_foods": top_foods, "shortfalls": shortfalls, "surpluses": surpluses,
            "partners": partners,
        })
    out.sort(key=lambda r: r["gdp_rank"] or 999)
    # Small summary for the overview table; full detail goes to one file per country.
    summary = []
    for c in out:
        cer = next((g for g in c["groups"] if g["group"] == "Cereals"), {})
        p = c["partners"] or {}
        top = (p.get("top") or [None])[0]
        summary.append({k: c[k] for k in ("iso3", "name", "flag", "region", "gdp_rank", "kcal", "protein",
                                           "animal_share", "kcal_10y_ago")} | {
            "cereal_dependency": cer.get("import_dependency"),
            "top_supplier": {"name": top["name"], "iso3": top["iso3"], "share": top["share"]} if top else None,
            "top_shortfall": c["shortfalls"][0]["item"] if c["shortfalls"] else None,
            "top_surplus": c["surpluses"][0]["item"] if c["surpluses"] else None,
            "food_imports_kusd": p.get("total_kusd"),
        })
    return {"year": fbs["year"], "trade_year": tm.get("year"), "countries": summary,
            "details": {c["iso3"]: c for c in out}}
