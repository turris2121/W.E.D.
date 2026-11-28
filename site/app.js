"use strict";

const state = { countries: [], meta: null, sort: { k: "population", asc: false }, days: 90 };
const $ = (s) => document.querySelector(s);

const KIND_CLASS = {
  "Presidential": "Presidential",
  "Legislative / general": "Legislative",
  "Referendum": "Referendum",
};
const kindClass = (k) => "k-" + (KIND_CLASS[k] || "Other");

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const na = '<span class="na">—</span>';

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
const fmtNum = (v) => (v == null ? na : compact.format(v));
const fmtUsd = (v) => (v == null ? na : "$" + compact.format(v));
const fmtRate = (v) => {
  if (v == null) return na;
  if (v >= 1000) return Math.round(v).toLocaleString("en");
  if (v >= 1) return v.toFixed(2);
  return v.toPrecision(3);
};
const fmtPct = (v) => (v == null ? na : v.toFixed(1) + "%");
// Share of world GDP: more decimals for small economies so they don't all read "0.0%".
const shareText = (v) => (v == null ? null : v >= 1 ? v.toFixed(1) + "%" : v >= 0.01 ? v.toFixed(2) + "%" : "<0.01%");
const fmtShare = (v) => shareText(v) ?? na;

function fmtDate(d) {
  if (!d) return na;
  const [y, m, day] = d.split("-");
  if (!m) return y;
  const mon = new Date(Date.UTC(+y, +m - 1, 1)).toLocaleString("en", { month: "short", timeZone: "UTC" });
  return day ? `${+day} ${mon} ${y}` : `${mon} ${y}`;
}

// Sort key for partial dates: "2027" -> "2027-12-31" would mislead, keep raw lexicographic.
const nextElection = (c) => {
  const e = c.politics.next_election;
  if (e) return { date: e.date, label: e.kind, est: false };
  const est = c.politics.legislature.chambers.map((x) => x.next_election_estimate).filter(Boolean).sort()[0];
  return est ? { date: est, label: "Legislative (est.)", est: true } : null;
};

const mainCurrency = (c) => c.economy.currencies[0] || null;

function sortValue(c, k) {
  const e = c.economy;
  switch (k) {
    case "name": return c.name;
    case "population": return e.population;
    case "gdp": return e.gdp_usd;
    case "gdppc": return e.gdp_per_capita;
    case "share": return e.world_gdp_share;
    case "currency": return mainCurrency(c)?.code;
    case "fx": return mainCurrency(c)?.per_usd;
    case "system": return c.politics.system_category;
    case "seats": return c.politics.legislature.total_seats;
    case "next": return nextElection(c)?.date;
  }
}

async function load() {
  try {
    const [countries, meta] = await Promise.all([
      fetch("data/countries.json", { cache: "no-cache" }).then((r) => r.json()),
      fetch("data/meta.json", { cache: "no-cache" }).then((r) => r.json()),
    ]);
    state.countries = countries;
    state.meta = meta;
  } catch (err) {
    $("#updated").textContent = "Could not load data. Run scripts/fetch_all.py first.";
    return;
  }
  initFilters();
  renderHeader();
  renderKpis();
  renderLegend();
  renderUpcoming();
  renderTable();
  renderFooter();
  if (typeof initTabs === "function") initTabs();
  openFromHash();
  if (typeof renderMonth === "function") renderMonth();
  if (typeof initBanks === "function") initBanks();
  if (typeof initTrade === "function") initTrade();
  if (typeof initLabour === "function") initLabour();
}

function renderHeader() {
  const m = state.meta;
  const when = new Date(m.generated_at);
  const bad = Object.entries(m.sources).filter(([, s]) => s.status === "stale" || s.status === "error");
  $("#updated").innerHTML =
    `Updated ${esc(when.toLocaleString("en", { dateStyle: "medium", timeStyle: "short" }))}` +
    (bad.length ? `<br><span class="warn">⚠ Using older data for: ${bad.map(([k]) => esc(k)).join(", ")}</span>` : "");
}

function allElections() {
  const out = [];
  for (const c of state.countries)
    for (const e of c.politics.elections) out.push({ ...e, country: c });
  return out;
}

function upcomingWithin(days) {
  const today = new Date().toISOString().slice(0, 10);
  const end = new Date(Date.now() + days * 864e5).toISOString().slice(0, 10);
  return allElections()
    .filter((e) => e.status === "upcoming" && e.date && e.date >= today.slice(0, e.date.length) && e.date <= end.slice(0, e.date.length))
    .sort((a, b) => (a.date + "~").localeCompare(b.date + "~"));
}

function renderKpis() {
  const cs = state.countries;
  const pop = cs.reduce((s, c) => s + (c.economy.population || 0), 0);
  const gdp = cs.reduce((s, c) => s + (c.economy.gdp_usd || 0), 0);
  const n90 = upcomingWithin(90).filter((e) => e.date_precision !== "year").length;
  const n365 = upcomingWithin(365).length;
  const tiles = [
    [cs.length, "Countries"],
    [compact.format(pop), "Total population"],
    ["$" + compact.format(gdp), "Combined GDP"],
    [n90, "Elections in the next 90 days"],
    [n365, "Elections in the next 12 months"],
  ];
  $("#kpis").innerHTML = tiles.map(([v, l]) => `<div class="kpi"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
}

function renderLegend() {
  $("#kind-legend").innerHTML = ["Presidential", "Legislative / general", "Referendum", "Other"]
    .map((k) => `<span><span class="dot ${kindClass(k)}"></span>${esc(k)}</span>`).join("");
}

function renderUpcoming() {
  const list = upcomingWithin(state.days);
  if (!list.length) { $("#upcoming").innerHTML = `<div class="empty">No elections with a known date in this window.</div>`; return; }
  const groups = new Map();
  for (const e of list) {
    const key = e.date.length >= 7 ? e.date.slice(0, 7) : e.date;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(e);
  }
  $("#upcoming").innerHTML = [...groups].map(([key, evs]) => `
    <div class="month"><h4>${esc(key.length === 4 ? key + " (date not yet set)" : fmtDate(key))}</h4>
      <div class="ev-list">${evs.map((e) => `
        <button class="ev" data-iso="${esc(e.country.iso3)}" title="${esc(e.name)}">
          <span class="flag">${esc(e.country.flag || "")}</span>
          <span><div class="t">${esc(e.country.name)}</div>
            <div class="s"><span class="dot ${kindClass(e.kind)}"></span>${esc(e.kind)}</div></span>
          <span class="date">${e.date_precision === "day" ? fmtDate(e.date) : ""}</span>
        </button>`).join("")}</div></div>`).join("");
}

function initFilters() {
  const regions = [...new Set(state.countries.map((c) => c.region).filter(Boolean))].sort();
  const systems = [...new Set(state.countries.map((c) => c.politics.system_category))].sort();
  $("#region").insertAdjacentHTML("beforeend", regions.map((r) => `<option>${esc(r)}</option>`).join(""));
  $("#system").insertAdjacentHTML("beforeend", systems.map((r) => `<option>${esc(r)}</option>`).join(""));
  for (const id of ["#q", "#region", "#system"]) $(id).addEventListener("input", renderTable);

  document.querySelectorAll("#tbl th").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.k;
    state.sort = { k, asc: state.sort.k === k ? !state.sort.asc : k === "name" || k === "next" };
    renderTable();
  }));
  document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b));
    state.days = +b.dataset.days;
    renderUpcoming();
  }));
  document.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-iso]");
    if (el) openDetail(el.dataset.iso);
  });
  $("#d-close").addEventListener("click", () => $("#detail").close());
  $("#detail").addEventListener("click", (ev) => { if (ev.target.id === "detail") $("#detail").close(); });
  // On close, go back to the active tab's address (e.g. #banks) instead of the country code.
  $("#detail").addEventListener("close", () =>
    history.replaceState(null, "", typeof tabHash === "function" ? tabHash() : location.pathname));
}

function filtered() {
  const q = $("#q").value.trim().toLowerCase();
  const region = $("#region").value;
  const system = $("#system").value;
  return state.countries.filter((c) => {
    if (region && c.region !== region) return false;
    if (system && c.politics.system_category !== system) return false;
    if (!q) return true;
    const p = c.politics;
    return [c.name, c.capital, c.iso3, p.head_of_state.name, p.head_of_government.name,
      ...c.economy.currencies.map((x) => x.code + " " + x.name)]
      .some((s) => s && s.toLowerCase().includes(q));
  });
}

function renderTable() {
  const { k, asc } = state.sort;
  const rows = filtered().sort((a, b) => {
    const va = sortValue(a, k), vb = sortValue(b, k);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    const r = typeof va === "string" ? va.localeCompare(vb) : va - vb;
    return asc ? r : -r;
  });
  document.querySelectorAll("#tbl th").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.k === k);
    th.classList.toggle("asc", th.dataset.k === k && asc);
  });
  $("#row-count").textContent = `${rows.length} of ${state.countries.length}`;
  $("#tbl tbody").innerHTML = rows.map((c) => {
    const e = c.economy, cur = mainCurrency(c), ne = nextElection(c);
    return `<tr data-iso="${esc(c.iso3)}">
      <td><span class="flag">${esc(c.flag || "")}</span>${esc(c.name)}</td>
      <td class="num">${fmtNum(e.population)}</td>
      <td class="num">${fmtUsd(e.gdp_usd)}</td>
      <td class="num">${fmtUsd(e.gdp_per_capita)}</td>
      <td class="num">${fmtShare(e.world_gdp_share)}</td>
      <td>${cur ? esc(cur.code) : na}</td>
      <td class="num">${cur ? fmtRate(cur.per_usd) : na}</td>
      <td class="sys">${esc(c.politics.system_category)}</td>
      <td class="num">${fmtNum(c.politics.legislature.total_seats)}</td>
      <td>${ne ? `${fmtDate(ne.date)} <span class="muted">${esc(ne.label)}</span>` : na}</td>
    </tr>`;
  }).join("");
}

function dl(pairs) {
  return `<dl>${pairs.filter(([, v]) => v != null && v !== "").map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;
}

function personCard(title, p, note) {
  return `<div class="card"><h3>${esc(title)}</h3>${dl([
    ["Office", p.title ? esc(p.title) : na],
    ["Current", p.name ? esc(p.name) : na],
    ["How chosen", p.selection ? esc(p.selection) : na],
    ["Term", p.term_years ? esc(p.term_years) + " years" : null],
    ["Note", note],
  ])}</div>`;
}

function openDetail(iso3) {
  const c = state.countries.find((x) => x.iso3 === iso3);
  if (!c) return;
  const e = c.economy, p = c.politics, leg = p.legislature;
  const yr = (y) => (y ? ` <span class="muted">(${y})</span>` : "");

  const econ = `<div class="card"><h3>Economy</h3>${dl([
    ["Population", fmtNum(e.population) + yr(e.population_year)],
    ["GDP", fmtUsd(e.gdp_usd) + yr(e.gdp_usd_year)],
    ["Economy size", e.gdp_rank ? `#${e.gdp_rank} of ${e.ranked_countries} countries` : na],
    ["World influence", fmtShare(e.world_gdp_share) + ' <span class="muted">of world GDP</span>'],
    ["Share of world population", fmtShare(e.world_pop_share)],
    ["GDP per capita", fmtUsd(e.gdp_per_capita) + yr(e.gdp_per_capita_year)],
    ["GDP growth", fmtPct(e.gdp_growth) + yr(e.gdp_growth_year)],
    ["Inflation", fmtPct(e.inflation) + yr(e.inflation_year)],
    ...e.currencies.map((cur) => [
      `Currency (${cur.code})`,
      `${esc(cur.name)}${cur.symbol ? " " + esc(cur.symbol) : ""}<br>` +
      (cur.per_usd ? `1 USD = ${fmtRate(cur.per_usd)} ${esc(cur.code)}<br>1 ${esc(cur.code)} = ${fmtRate(cur.usd_value)} USD` : na) +
      (e.fx_date ? ` <span class="muted">(${esc(e.fx_date)})</span>` : ""),
    ]),
  ])}</div>`;

  const system = `<div class="card"><h3>Political system</h3>${dl([
    ["Category", esc(p.system_category)],
    ["Form of government", p.system.length ? esc(p.system.join(", ")) : na],
    ["Legislature", leg.name ? esc(leg.name) : na],
    ["Structure", leg.structure ? esc(leg.structure) : null],
    ["Total seats", leg.total_seats ? fmtNum(leg.total_seats) : null],
  ])}</div>`;

  const chambers = leg.chambers.length ? `<div class="card wide"><h3>Legislature: how seats are filled</h3><div class="chambers">${
    leg.chambers.map((ch) => `<div class="chamber">
      <div><strong>${esc(ch.name || "Chamber")}</strong> <span class="muted">${esc(ch.role || "")}</span>${ch.suspended ? ' <span class="badge">suspended</span>' : ""}</div>
      <div class="seats">${ch.seats ?? "—"} <span class="muted">seats</span></div>
      ${dl([
        ["How members are chosen", ch.how_chosen ? esc(ch.how_chosen) : null],
        ["Directly elected", ch.directly_elected != null ? esc(ch.directly_elected) : null],
        ["Electoral system", [ch.electoral_system, ch.electoral_subsystem].filter(Boolean).map(esc).join(" → ") || null],
        ["Term", ch.term_years ? esc(ch.term_years) + " years" : null],
        ["Last election", ch.last_election ? fmtDate(ch.last_election) : null],
        ["Next (estimated)", ch.next_election_estimate ? esc(ch.next_election_estimate) + ' <span class="muted">last election + term</span>' : null],
        ["Women", ch.women_percent != null ? fmtPct(ch.women_percent) : null],
        ["Voting age", ch.voting_age ? esc(ch.voting_age) : null],
      ])}</div>`).join("")}</div>
      <p class="muted" style="margin-top:8px">Source: <a href="${esc(leg.chambers[0].ipu)}" target="_blank" rel="noopener">IPU Parline</a></p></div>` : "";

  const els = p.elections.slice().sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  const elections = `<div class="card wide"><h3>Elections (last 2 years &amp; upcoming)</h3>${
    els.length ? els.map((x) => `<div class="el-row">
      <span class="date">${fmtDate(x.date)}</span>
      <span><span class="dot ${kindClass(x.kind)}"></span><a href="${esc(x.wikidata)}" target="_blank" rel="noopener">${esc(x.name)}</a>
      <span class="badge ${esc(x.status)}">${esc(x.status)}</span>
      ${x.winners.length ? `<div class="muted">Winner: ${esc(x.winners.join(", "))}</div>` : ""}</span>
    </div>`).join("") : `<div class="empty">No national elections recorded in Wikidata for this window.</div>`}</div>`;

  $("#d-body").innerHTML = `
    <div class="d-head"><span class="flag">${esc(c.flag || "")}</span>
      <div><h2 id="d-title">${esc(c.name)}</h2>
      <div class="muted">${c.capital ? "Capital: " + esc(c.capital) : ""}${c.income_level ? " · " + esc(c.income_level) : ""}</div></div></div>
    <div class="cards">
      ${econ}${system}
      ${personCard("Head of state", p.head_of_state, p.same_person ? "Also head of government" : null)}
      ${p.same_person ? "" : personCard("Head of government", p.head_of_government)}
      ${chambers}${elections}
    </div>
    ${typeof bankLinkFor === "function" ? bankLinkFor(c.iso3) : ""}
    ${typeof tradeLinkFor === "function" ? tradeLinkFor(c.iso3) : ""}
    ${c.wikidata ? `<p class="muted" style="margin-top:12px">Political data: <a href="${esc(c.wikidata)}" target="_blank" rel="noopener">Wikidata</a>. Spot an error? Add a correction in <code>scripts/overrides.json</code>.</p>` : ""}`;
  history.replaceState(null, "", "#" + c.iso3);
  const d = $("#detail");
  if (!d.open) d.showModal();
  d.scrollTop = 0;
}

function openFromHash() {
  const iso = location.hash.slice(1);
  if (/^[A-Z]{3}$/.test(iso)) openDetail(iso); // tab hashes (#banks, #banks/JP) are lowercase
}

function renderFooter() {
  const m = state.meta;
  const names = { countries: "Wikidata + World Bank (country list, capitals, currencies, regions)", worldbank: "World Bank (population, GDP)",
    fx: "ExchangeRate-API open access (USD rates)", politics: "Wikidata (government, leaders)",
    elections: "Wikidata (elections)", ipu: "IPU Parline (parliaments)", bis: "BIS (policy rates, CPI, FX)",
    trade: "UN Comtrade (goods trade)", tariffs: "World Bank + OECD (tariffs, taxes)", us_customs: "US Treasury + UN Comtrade (US customs duties)" };
  $("#foot").innerHTML = `<strong>Sources</strong><ul>${Object.entries(m.sources).map(([k, s]) =>
    `<li>${esc(names[k] || k)} · ${esc(s.status)}${s.fetched_at ? " · fetched " + esc(s.fetched_at.slice(0, 10)) : ""}</li>`).join("")}</ul>
    World Bank figures are the latest available year (usually 1–2 years behind). Election dates shown as a year only are not yet fixed.
    IPU data © Inter-Parliamentary Union, CC BY-NC-SA 4.0.`;
}

load();
