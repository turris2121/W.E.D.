"use strict";
/* Trade tab: what the largest economies sell each other, by sector, plus tariffs and taxes.
   Uses esc, compact, fmtDate, na from app.js and tabState / setTabSub from tabs.js.
   Data: data/trade.json, built by scripts/trade.py. */

const tr = { data: null, E: {}, iso: "USA", pair: null, mode: "value" };
const money = (v) => (v == null ? na : (v < 0 ? "−$" : "$") + compact.format(Math.abs(v)));
const pct1 = (v) => (v == null ? na : v.toFixed(1) + "%");
const chg = (v) => {
  if (v == null) return '<span class="na">—</span>';
  const cls = v > 0.5 ? "up" : v < -0.5 ? "down" : "flat";
  const arrow = v > 0.5 ? "▲" : v < -0.5 ? "▼" : "▶";
  return `<span class="chg ${cls}" title="Change on the year before"><span aria-hidden="true">${arrow}</span> ${v > 0 ? "+" : ""}${v.toFixed(0)}%</span>`;
};
const nameOf = (iso) => tr.E[iso]?.name || iso;
const flagOf = (iso) => tr.E[iso]?.flag || "";
const pairKey = (a, b) => {
  const order = tr.data.economies.map((e) => e.iso3);
  return order.indexOf(a) < order.indexOf(b) ? `${a}-${b}` : `${b}-${a}`;
};

/* ---------- tooltip (shared #tip element from index.html) ---------- */
function trTip(html, ev) {
  const t = document.getElementById("tip");
  t.innerHTML = html;
  t.hidden = false;
  const pad = 14, w = t.offsetWidth, h = t.offsetHeight;
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + w > innerWidth - 8) x = ev.clientX - w - pad;
  if (y + h > innerHeight - 8) y = ev.clientY - h - pad;
  t.style.left = Math.max(8, x) + "px";
  t.style.top = Math.max(8, y) + "px";
}
const trTipHide = () => { document.getElementById("tip").hidden = true; };

/* ---------- entry ---------- */
async function initTrade() {
  try {
    tr.data = await fetch("data/trade.json", { cache: "no-cache" }).then((r) => r.json());
  } catch {
    document.getElementById("pane-trade").insertAdjacentHTML("afterbegin",
      '<div class="panel empty">Trade data not available yet. Run scripts/fetch_all.py.</div>');
    return;
  }
  for (const e of tr.data.economies) tr.E[e.iso3] = e;
  const top = Object.values(tr.data.pairs).sort((a, b) => b.total - a.total)[0];
  tr.pair = top ? `${top.a}-${top.b}` : null;

  renderTradeKpis();
  renderInsights();
  renderPicker();
  renderMatrix();
  renderRca();
  renderUsTariff();
  wireTrade();
  applyTradeSub(tabState.active === "trade" ? tabState.sub : "");
  document.addEventListener("tabshow", (ev) => {
    if (ev.detail.name === "trade") { applyTradeSub(ev.detail.sub); renderUsTariff(); }
  });
}

function applyTradeSub(sub) {
  if (/^[A-Z]{3}-[A-Z]{3}$/.test(sub || "")) {
    const [a, b] = sub.split("-");
    if (tr.data.pairs[pairKey(a, b)]) tr.pair = pairKey(a, b);
  } else if (/^[A-Z]{3}$/.test(sub || "") && tr.E[sub]) {
    tr.iso = sub;
  }
  renderCountry();
  renderPair();
}

function wireTrade() {
  const pane = document.getElementById("pane-trade");
  pane.addEventListener("click", (ev) => {
    const c = ev.target.closest("[data-tr-country]");
    const p = ev.target.closest("[data-tr-pair]");
    const go = ev.target.closest("[data-tr-go]");
    if (c) selectCountry(c.dataset.trCountry, c.hasAttribute("data-scroll"));
    else if (p) selectPair(p.dataset.trPair, true);
    else if (go) {
      const [kind, val] = go.dataset.trGo.split("/");
      if (kind === "country") selectCountry(val, true);
      else if (kind === "pair") selectPair(val, true);
      else document.getElementById("tr-us").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  document.querySelectorAll("#tr-mode button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#tr-mode button").forEach((x) => x.classList.toggle("on", x === b));
    tr.mode = b.dataset.mode;
    renderMatrix();
  }));
  pane.addEventListener("mouseleave", trTipHide);
  addEventListener("resize", () => { if (tabState.active === "trade") renderUsTariff(); });
}

function selectCountry(iso, scroll) {
  if (!tr.E[iso]) return;
  tr.iso = iso;
  setTabSub(iso);
  renderCountry();
  if (scroll) document.getElementById("tr-country").scrollIntoView({ behavior: "smooth", block: "start" });
}

function selectPair(key, scroll) {
  const [a, b] = key.split("-");
  const k = pairKey(a, b);
  if (!tr.data.pairs[k]) return;
  tr.pair = k;
  setTabSub(k);
  renderPair();
  renderMatrix();
  if (scroll) document.getElementById("tr-pair").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- KPIs + insights ---------- */
function renderTradeKpis() {
  const d = tr.data, es = d.economies;
  const exp = es.reduce((s, e) => s + (e.exports || 0), 0);
  const top = Object.values(d.pairs).sort((a, b) => b.total - a.total)[0];
  const us = d.us_tariff?.latest;
  const firstCn = es.filter((e) => e.export_partners[0]?.iso3 === "CHN").length;
  const firstUs = es.filter((e) => e.export_partners[0]?.iso3 === "USA").length;
  const years = [...new Set(es.filter((e) => !e.mirror).map((e) => e.year))].sort();
  const tiles = [
    [money(exp), `Goods exported by these ${es.length} economies (${years.join("/")})`],
    [top ? `${flagOf(top.a)} ${flagOf(top.b)} ${money(top.total)}` : na, top ? `Biggest relationship: ${nameOf(top.a)}–${nameOf(top.b)}` : ""],
    [us ? us.rate.toFixed(1) + "%" : na, us ? `US effective tariff rate (${fmtDate(us.month)})` : "US effective tariff rate"],
    [`${firstUs} vs ${firstCn}`, "Economies whose #1 export market is the US vs China"],
  ];
  document.getElementById("tr-kpis").innerHTML = tiles.map(([v, l]) =>
    `<div class="kpi"><div class="v">${v}</div><div class="l">${esc(l)}</div></div>`).join("");
  document.getElementById("tr-asof").textContent =
    `Goods trade ${years.join("/")} · UN Comtrade`;
  if (!d.complete) {
    document.getElementById("tr-kpis").insertAdjacentHTML("beforebegin",
      `<div class="panel warn-note" role="status">⚠ Still downloading: ${es.length} of 15 economies so far. UN Comtrade limits free downloads per day, so the rest arrive on the next daily update.</div>`);
  }
}

const INSIGHT_ICON = { relationship: "⇄", balance: "±", dependence: "◎", shift: "↗", structure: "▦", tariff: "%", tax: "§" };
function renderInsights() {
  document.getElementById("tr-insights").innerHTML = tr.data.insights.map((i) => `
    <article class="insight">
      <div class="in-ic" aria-hidden="true">${esc(INSIGHT_ICON[i.kind] || "•")}</div>
      <div><h4>${esc(i.title)}</h4><p>${esc(i.text)}</p>
      ${i.link ? `<button class="linkbtn" data-tr-go="${esc(i.link)}">Show me →</button>` : ""}</div>
    </article>`).join("");
}

/* ---------- country profile ---------- */
function renderPicker() {
  document.getElementById("tr-picker").innerHTML = tr.data.economies.map((e) =>
    `<button class="pick" data-tr-country="${esc(e.iso3)}" aria-pressed="false"><span class="flag">${esc(e.flag || "")}</span>${esc(e.name)}</button>`).join("");
}

function barList(items, total, cls, maxItems = 10) {
  let rows = items.slice(0, maxItems);
  const rest = items.slice(maxItems);
  if (rest.length) {
    const v = rest.reduce((s, x) => s + x.value, 0);
    rows = rows.concat([{ sector: `${rest.length} other sectors`, name: `${rest.length} more`, value: v, share: total ? 100 * v / total : null, folded: true }]);
  }
  const max = Math.max(...rows.map((r) => r.share || 0), 1);
  return `<div class="bars">${rows.map((r, i) => `
    <div class="bar-row${r.folded ? " folded" : ""}${i === 0 && !r.folded ? " lead" : ""}">
      <span class="bl">${esc(r.sector || r.name)}</span>
      <span class="bt"><span class="bf ${cls}" style="width:${Math.max(1, (100 * (r.share || 0)) / max)}%"></span></span>
      <span class="bp">${pct1(r.share)}</span>
      <span class="bv">${money(r.value)}</span>
    </div>`).join("")}</div>`;
}

function productTable(items, cls) {
  const max = Math.max(...items.map((p) => p.share || 0), 1);
  return `<ol class="prod">${items.slice(0, 10).map((p) => `
    <li><span class="pn"><span class="hs">HS ${esc(p.hs.padStart(2, "0"))}</span> ${esc(p.name)}</span>
      <span class="bt"><span class="bf ${cls}" style="width:${(100 * (p.share || 0)) / max}%"></span></span>
      <span class="bp">${pct1(p.share)}</span><span class="bv">${money(p.value)}</span></li>`).join("")}</ol>`;
}

function partnerList(list, iso) {
  return `<ol class="partners">${list.map((p) => {
    const pairable = p.major && p.iso3 !== iso;
    const inner = `<span class="flag">${esc(p.flag || "")}</span><span class="pn">${esc(p.name)}</span>
      <span class="bp">${pct1(p.share)}</span><span class="bv">${money(p.value)}</span>${chg(p.change_pct)}`;
    return `<li>${pairable ? `<button class="prow" data-tr-pair="${esc(pairKey(iso, p.iso3))}" title="Open the ${esc(nameOf(iso))}–${esc(p.name)} relationship">${inner}</button>`
      : `<div class="prow">${inner}</div>`}</li>`;
  }).join("")}</ol>`;
}

function taxCard(e) {
  const t = e.taxes, yr = (x) => (x ? ` <span class="muted">(${x.year})</span>` : "");
  const v = (x, f = pct1) => (x ? f(x.value) + yr(x) : na);
  const isEu = tr.data.eu27.includes(e.iso3);
  return `<div class="card"><h3>Tariffs it charges</h3>${dl([
    ["Average applied tariff (trade-weighted)", v(t.tariff_weighted)],
    ["Average applied tariff (simple)", v(t.tariff_simple)],
    ["Most-favoured-nation rate (weighted)", v(t.tariff_mfn_weighted)],
    ["On manufactured goods", v(t.tariff_manufactured)],
    ["On primary goods", v(t.tariff_primary)],
  ])}
  <p class="muted small">${isEu ? "EU members share one external tariff, set in Brussels. " : ""}World Bank/WITS averages lag 2–4 years and leave out special duties (e.g. US Section 301 and 2025 emergency tariffs, retaliation).${e.iso3 === "USA" ? ' See the <button class="linkbtn" data-tr-go="us-tariff">live US effective rate</button>.' : ""}</p></div>
  <div class="card"><h3>Taxes</h3>${dl([
    ["Corporate income tax (statutory)", v(t.corporate_tax)],
    ["Tax revenue, % of GDP", v(t.tax_revenue_pct_gdp)],
    ["Trade taxes, % of revenue", v(t.trade_taxes_pct_revenue)],
  ])}<p class="muted small">Corporate rate: OECD, combined central + sub-national. Tax revenue is central government only.</p></div>`;
}

function renderCountry() {
  const e = tr.E[tr.iso];
  if (!e) return;
  document.querySelectorAll("#tr-picker .pick").forEach((b) => b.setAttribute("aria-pressed", b.dataset.trCountry === e.iso3 ? "true" : "false"));
  const t = e.taxes;
  const services = t.services_exports ? money(t.services_exports.value) + ` <span class="muted">(${t.services_exports.year})</span>` : na;
  const topP = e.export_partners[0];
  const bloc = e.export_bloc_share;
  const blocTxt = ["USA", "CHN", "EU"].filter((k) => bloc[k] != null && !(k === "USA" && e.iso3 === "USA") && !(k === "CHN" && e.iso3 === "CHN"))
    .map((k) => `${k === "USA" ? "US" : k === "CHN" ? "China" : "EU"} ${bloc[k].toFixed(0)}%`).join(" · ");
  const stats = [
    ["Goods exports", money(e.exports) + (e.exports_change_pct != null ? " " + chg(e.exports_change_pct) : "")],
    ["Goods imports", money(e.imports)],
    ["Trade balance", `<span class="${e.balance >= 0 ? "pos" : "neg"}">${e.balance >= 0 ? "Surplus" : "Deficit"} ${money(Math.abs(e.balance))}</span>`],
    ["Trade, % of GDP", t.trade_pct_gdp ? pct1(t.trade_pct_gdp.value) + ` <span class="muted">(${t.trade_pct_gdp.year}, incl. services)</span>` : na],
    ["Services exports", services],
    ["#1 customer", topP ? `${esc(topP.flag || "")} ${esc(topP.name)} <span class="muted">${pct1(topP.share)}</span>` : na],
    ["Exports go to", blocTxt || na],
  ];
  document.getElementById("tr-cbody").innerHTML = `
    <div class="bd-head"><span class="bd-flag">${esc(e.flag || "")}</span>
      <div><h2>${esc(e.name)}</h2><div class="muted">Goods trade in ${e.year}${e.mirror
        ? " · <strong>mirror data</strong>: Russia stopped reporting to the UN, so this is what the other 14 economies report buying from and selling to it. Its trade with other countries (e.g. Türkiye, Kazakhstan) is missing." : ""}</div></div></div>
    <div class="bd-stats">${stats.map(([l, v]) => `<div><span class="l">${esc(l)}</span><span class="v">${v}</span></div>`).join("")}</div>
    <div class="two">
      <div><h3><span class="sw ex"></span>What it sells: exports by sector</h3>${barList(e.exports_by_sector, e.exports, "ex")}</div>
      <div><h3><span class="sw im"></span>What it buys: imports by sector</h3>${barList(e.imports_by_sector, e.imports, "im")}</div>
    </div>
    <div class="two">
      <div><h3>Top export products <span class="muted">(HS chapter, % of exports)</span></h3>${productTable(e.top_exports, "ex")}</div>
      <div><h3>Top import products <span class="muted">(HS chapter, % of imports)</span></h3>${productTable(e.top_imports, "im")}</div>
    </div>
    <div class="two">
      <div><h3>Where it sells <span class="muted">(top 10, change on year)</span></h3>${partnerList(e.export_partners, e.iso3)}</div>
      <div><h3>Where it buys <span class="muted">(top 10, change on year)</span></h3>${partnerList(e.import_partners, e.iso3)}</div>
    </div>
    <div class="cards tax-cards">${taxCard(e)}</div>
    <p class="muted small">Click a major partner to see that relationship. Values are in current US dollars as reported to UN Comtrade (exports f.o.b., imports usually c.i.f.), so A's exports to B and B's imports from A rarely match exactly.</p>`;
}

/* ---------- relationship matrix (heatmap) ---------- */
const SEQ = 7;
function seqBin(v, lo, hi) {
  if (!v || v <= 0) return 0;
  const t = (Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo));
  return Math.max(1, Math.min(SEQ, Math.ceil(t * SEQ)));
}

function renderMatrix() {
  const d = tr.data, isos = d.economies.map((e) => e.iso3);
  const val = (a, b) => {
    const v = d.matrix[a]?.[b];
    if (v == null) return null;
    return tr.mode === "share" ? (tr.E[a].exports ? (100 * v) / tr.E[a].exports : null) : v;
  };
  const vals = isos.flatMap((a) => isos.filter((b) => b !== a).map((b) => val(a, b))).filter((v) => v > 0);
  const lo = tr.mode === "share" ? 0.3 : 1e9, hi = Math.max(...vals);
  const [pa, pb] = (tr.pair || "-").split("-");
  const fmt = (v) => (tr.mode === "share" ? (v >= 10 ? v.toFixed(0) : v.toFixed(1)) + "%" : "$" + compact.format(v));
  const head = `<tr><th class="corner" scope="col"><span>exporter ↓</span><span>buyer →</span></th>${isos.map((b) =>
    `<th scope="col" title="${esc(nameOf(b))}"><span class="flag">${esc(flagOf(b))}</span><span class="iso">${esc(b)}</span></th>`).join("")}</tr>`;
  const body = isos.map((a) => `<tr><th scope="row" title="${esc(nameOf(a))}"><span class="flag">${esc(flagOf(a))}</span><span class="iso">${esc(a)}</span></th>${
    isos.map((b) => {
      if (a === b) return `<td class="self" aria-hidden="true"></td>`;
      const v = val(a, b);
      const on = (a === pa && b === pb) || (a === pb && b === pa);
      return `<td class="hm s${seqBin(v, lo, hi)}${on ? " on" : ""}" data-a="${a}" data-b="${b}" data-tr-pair="${pairKey(a, b)}"
        tabindex="0" aria-label="${esc(nameOf(a))} to ${esc(nameOf(b))}: ${v == null ? "no data" : fmt(v)}">${v == null ? "" : fmt(v)}</td>`;
    }).join("")}</tr>`).join("");
  const el = document.getElementById("tr-matrix");
  el.innerHTML = `<table class="heat"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  document.getElementById("tr-matrix-legend").innerHTML =
    `<span>${tr.mode === "share" ? "Share of the exporter's goods exports" : "Value of goods exported in a year"}:</span>
     <span class="ramp">${Array.from({ length: SEQ }, (_, i) => `<span class="s${i + 1}"></span>`).join("")}</span>
     <span>${tr.mode === "share" ? `≤${lo}%` : "≤$1B"} → ${fmt(hi)}</span><span class="muted">(log scale)</span>`;
  el.querySelectorAll("td.hm").forEach((td) => {
    const show = (ev) => {
      const a = td.dataset.a, b = td.dataset.b, v = d.matrix[a]?.[b];
      const p = d.pairs[pairKey(a, b)];
      const change = p ? (p.a === a ? p.ab_change_pct : p.ba_change_pct) : null;
      trTip(`<strong>${esc(flagOf(a))} ${esc(nameOf(a))} → ${esc(flagOf(b))} ${esc(nameOf(b))}</strong><br>
        ${money(v)} · ${v && tr.E[a].exports ? pct1((100 * v) / tr.E[a].exports) : "—"} of ${esc(nameOf(a))}'s exports<br>
        Change on year: ${change == null ? "—" : (change > 0 ? "+" : "") + change.toFixed(0) + "%"}
        ${a === "RUS" ? '<br><span class="muted">Mirror data (partner-reported)</span>' : ""}<br><span class="muted">Click for details</span>`, ev);
    };
    td.addEventListener("mousemove", show);
    td.addEventListener("mouseleave", trTipHide);
    td.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); selectPair(td.dataset.trPair, true); } });
  });
}

/* ---------- pair detail ---------- */
function renderPair() {
  const p = tr.data.pairs[tr.pair];
  const el = document.getElementById("tr-pair");
  if (!p) { el.innerHTML = '<div class="empty">Click a cell in the matrix to compare two economies.</div>'; return; }
  const A = tr.E[p.a], B = tr.E[p.b];
  const ab = p.ab.value || 0, ba = p.ba.value || 0, bal = ab - ba;
  const sectors = new Map();
  for (const s of p.ab.sectors) sectors.set(s.sector, { sector: s.sector, ab: s.value, ba: 0 });
  for (const s of p.ba.sectors) { const x = sectors.get(s.sector) || { sector: s.sector, ab: 0, ba: 0 }; x.ba = s.value; sectors.set(s.sector, x); }
  const rows = [...sectors.values()].sort((x, y) => (y.ab + y.ba) - (x.ab + x.ba)).slice(0, 12);
  const max = Math.max(...rows.map((r) => Math.max(r.ab, r.ba)), 1);
  const abTot = p.ab.sectors.reduce((s, x) => s + x.value, 0) || 1, baTot = p.ba.sectors.reduce((s, x) => s + x.value, 0) || 1;
  const products = (side, cls) => side.products.length ? `<ol class="prod">${side.products.map((x) => `
      <li><span class="pn"><span class="hs">HS ${esc(x.hs.padStart(2, "0"))}</span> ${esc(x.name)}</span>
      <span class="bt"><span class="bf ${cls}" style="width:${x.share || 0}%"></span></span>
      <span class="bp">${pct1(x.share)}</span><span class="bv">${money(x.value)}</span></li>`).join("")}</ol>`
    : '<div class="empty">No product breakdown reported.</div>';
  const mirrorNote = p.a === "RUS" || p.b === "RUS" ? '<p class="muted small">Russia’s side is mirror data: what its partner reports.</p>' : "";
  el.innerHTML = `
    <div class="panel-head"><h2>${esc(A.flag || "")} ${esc(A.name)} ⇄ ${esc(B.flag || "")} ${esc(B.name)}</h2>
      <span class="muted">Total ${money(p.total)} · click any cell above to change</span></div>
    <div class="bd-stats">
      <div><span class="l">${esc(A.name)} sells to ${esc(B.name)}</span><span class="v">${money(ab)} ${chg(p.ab_change_pct)}</span></div>
      <div><span class="l">${esc(B.name)} sells to ${esc(A.name)}</span><span class="v">${money(ba)} ${chg(p.ba_change_pct)}</span></div>
      <div><span class="l">Balance</span><span class="v">${esc(bal >= 0 ? A.name : B.name)} surplus ${money(Math.abs(bal))}</span></div>
      <div><span class="l">Weight in each other's exports</span><span class="v">${pct1(A.exports ? 100 * ab / A.exports : null)} <span class="muted">of ${esc(A.name)}'s</span> · ${pct1(B.exports ? 100 * ba / B.exports : null)} <span class="muted">of ${esc(B.name)}'s</span></span></div>
    </div>
    <h3>What flows each way, by sector</h3>
    <div class="legend"><span><span class="sw ex"></span>${esc(A.name)} → ${esc(B.name)}</span><span><span class="sw im"></span>${esc(B.name)} → ${esc(A.name)}</span></div>
    <div class="b2b" role="table" aria-label="Trade by sector in both directions">
      ${rows.map((r) => `<div class="b2b-row" role="row" data-tip="${esc(r.sector)}|${r.ab}|${r.ba}">
        <span class="bv l" role="cell">${r.ab ? money(r.ab) : ""}</span>
        <span class="bt l"><span class="bf ex" style="width:${(100 * r.ab) / max}%"></span></span>
        <span class="bl" role="rowheader">${esc(r.sector)}</span>
        <span class="bt"><span class="bf im" style="width:${(100 * r.ba) / max}%"></span></span>
        <span class="bv" role="cell">${r.ba ? money(r.ba) : ""}</span></div>`).join("")}
    </div>
    <div class="two" style="margin-top:14px">
      <div><h3>Top products ${esc(A.name)} → ${esc(B.name)}</h3>${products(p.ab, "ex")}</div>
      <div><h3>Top products ${esc(B.name)} → ${esc(A.name)}</h3>${products(p.ba, "im")}</div>
    </div>${mirrorNote}`;
  el.querySelectorAll(".b2b-row").forEach((row) => {
    row.addEventListener("mousemove", (ev) => {
      const [s, x, y] = row.dataset.tip.split("|");
      trTip(`<strong>${esc(s)}</strong><br><span class="sw ex"></span>${esc(A.name)} → ${esc(B.name)}: ${money(+x)} (${pct1(100 * x / abTot)})<br>
        <span class="sw im"></span>${esc(B.name)} → ${esc(A.name)}: ${money(+y)} (${pct1(100 * y / baTot)})`, ev);
    });
    row.addEventListener("mouseleave", trTipHide);
  });
}

/* ---------- specialisation heatmap (revealed comparative advantage) ---------- */
function rcaBin(v) {
  if (v == null) return "n";
  if (v >= 3) return "p3"; if (v >= 1.75) return "p2"; if (v >= 1.2) return "p1";
  if (v > 0.83) return "z"; if (v > 0.57) return "m1"; if (v > 0.33) return "m2"; return "m3";
}
function renderRca() {
  const d = tr.data;
  const sectors = d.sector_order.filter((s) => !s.startsWith("Other /"));
  const es = d.economies.filter((e) => !e.mirror);
  const head = `<tr><th class="corner"></th>${sectors.map((s) => `<th scope="col" class="rot"><span>${esc(s)}</span></th>`).join("")}</tr>`;
  const body = es.map((e) => `<tr><th scope="row"><button class="linkbtn plain" data-tr-country="${esc(e.iso3)}" data-scroll><span class="flag">${esc(e.flag || "")}</span>${esc(e.name)}</button></th>${
    sectors.map((s) => {
      const v = e.rca[s], sh = e.exports_by_sector.find((x) => x.sector === s)?.share;
      return `<td class="rc r-${rcaBin(v)}" data-tip="${esc(e.name)}|${esc(s)}|${v ?? ""}|${sh ?? ""}">${v == null ? "" : v >= 10 ? Math.round(v) : v.toFixed(1)}</td>`;
    }).join("")}</tr>`).join("");
  const el = document.getElementById("tr-rca");
  el.innerHTML = `<table class="heat rca"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  el.querySelectorAll("td.rc").forEach((td) => {
    td.addEventListener("mousemove", (ev) => {
      const [n, s, v, sh] = td.dataset.tip.split("|");
      trTip(`<strong>${esc(n)} · ${esc(s)}</strong><br>${sh ? (+sh).toFixed(1) + "% of its exports" : "—"}<br>
        ${v ? (+v).toFixed(2) + "× the group average share" : "no exports reported"}`, ev);
    });
    td.addEventListener("mouseleave", trTipHide);
  });
}

/* ---------- US effective tariff rate (line chart) ---------- */
function renderUsTariff() {
  const us = tr.data?.us_tariff;
  const box = document.getElementById("tr-uschart");
  if (!us || !us.latest || !box) return;
  const rows = us.monthly.filter((r) => r.rate != null);
  const l = us.latest;
  const yoy = us.duties_prev_12m ? (100 * (us.duties_12m - us.duties_prev_12m)) / us.duties_prev_12m : null;
  document.getElementById("tr-us-stats").innerHTML = `
    <div><span class="l">Effective rate, ${esc(fmtDate(l.month))}</span><span class="v">${l.rate.toFixed(1)}%</span></div>
    <div><span class="l">Customs duties, last 12 months</span><span class="v">${money(us.duties_12m)} ${chg(yoy)}</span></div>
    <div><span class="l">Latest monthly duties (${esc(fmtDate(us.latest_duties_month.month))})</span><span class="v">${money(us.latest_duties_month.duties)}</span></div>
    <div><span class="l">Refunds paid back, last 12 months</span><span class="v">${money(us.refunds_12m)}</span></div>`;
  if (tabState.active !== "trade" || !box.clientWidth) return;

  const W = box.clientWidth, H = Math.max(220, Math.min(300, W * 0.4));
  const m = { t: 16, r: 54, b: 28, l: 40 };
  const parse = (s) => new Date(Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, 15));
  const x = d3.scaleUtc().domain(d3.extent(us.monthly, (r) => parse(r.month))).range([m.l, W - m.r]);
  const y = d3.scaleLinear().domain([0, Math.ceil(d3.max(rows, (r) => r.rate) + 1)]).nice().range([H - m.b, m.t]);
  const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
    .attr("aria-label", `US customs duties as a share of goods imports, monthly. Latest ${l.rate.toFixed(1)}% in ${fmtDate(l.month)}.`);
  svg.append("g").attr("class", "grid").selectAll("line").data(y.ticks(5)).join("line")
    .attr("x1", m.l).attr("x2", W - m.r).attr("y1", y).attr("y2", y);
  svg.append("g").attr("class", "yax").selectAll("text").data(y.ticks(5)).join("text")
    .attr("x", m.l - 6).attr("y", (v) => y(v) + 4).attr("text-anchor", "end").text((v) => v + "%");
  svg.append("g").attr("class", "xax").selectAll("text").data(x.ticks(W < 500 ? 4 : 8)).join("text")
    .attr("x", x).attr("y", H - 8).attr("text-anchor", "middle")
    .text((dt) => dt.toLocaleString("en", { month: "short", year: "2-digit", timeZone: "UTC" }));
  const line = d3.line().defined((r) => r.rate != null).x((r) => x(parse(r.month))).y((r) => y(r.rate));
  svg.append("path").datum(us.monthly).attr("class", "series").attr("stroke", "var(--k-pres)").attr("d", line);
  svg.append("circle").attr("cx", x(parse(l.month))).attr("cy", y(l.rate)).attr("r", 4).attr("class", "hdot").attr("fill", "var(--k-pres)");
  svg.append("text").attr("class", "dlabel").attr("x", x(parse(l.month)) + 8).attr("y", y(l.rate) + 4).text(l.rate.toFixed(1) + "%");
  const cross = svg.append("line").attr("class", "cross").attr("y1", m.t).attr("y2", H - m.b).style("display", "none");
  const dot = svg.append("circle").attr("r", 5).attr("class", "hdot").attr("fill", "var(--k-pres)").style("display", "none");
  svg.append("rect").attr("x", m.l).attr("y", m.t).attr("width", W - m.l - m.r).attr("height", H - m.t - m.b)
    .attr("fill", "transparent")
    .on("mousemove", (ev) => {
      const [px] = d3.pointer(ev);
      const t = x.invert(px);
      const r = rows.reduce((best, r) => (Math.abs(parse(r.month) - t) < Math.abs(parse(best.month) - t) ? r : best), rows[0]);
      cross.style("display", null).attr("x1", x(parse(r.month))).attr("x2", x(parse(r.month)));
      dot.style("display", null).attr("cx", x(parse(r.month))).attr("cy", y(r.rate));
      trTip(`<strong>${esc(fmtDate(r.month))}</strong><br>Effective rate ${r.rate.toFixed(2)}%<br>
        Duties collected ${money(r.duties)} · imports ${money(r.imports)}${r.refunds ? `<br>Refunds paid ${money(r.refunds)}` : ""}`, ev);
    })
    .on("mouseleave", () => { cross.style("display", "none"); dot.style("display", "none"); trTipHide(); });
  box.replaceChildren(svg.node());
}
