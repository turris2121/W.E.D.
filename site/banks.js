"use strict";
/* Tabs + Central banks tab: cards, comparison table, IS-LM diagram, history charts.
   Uses `state`, `esc`, `fmtDate`, `openDetail`, `$` from app.js; d3 from CDN. */

const bankState = { list: [], sort: { k: "world_gdp_share", asc: false }, sel: null, tab: "elections" };

// ------------------------------------------------------------------ tabs
const TABS = ["elections", "countries", "banks"];

function tabHash() {
  return "#" + bankState.tab + (bankState.tab === "banks" && bankState.sel ? "/" + bankState.sel : "");
}

function activateTab(tab, { push = true } = {}) {
  if (!TABS.includes(tab)) tab = "elections";
  bankState.tab = tab;
  document.querySelectorAll(".tabs [role=tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  TABS.forEach((t) => { document.getElementById("pane-" + t).hidden = t !== tab; });
  if (push && !document.getElementById("detail").open) history.replaceState(null, "", tabHash());
}

function initTabs() {
  const h = location.hash.slice(1);
  const [tab, sel] = h.split("/");
  if (TABS.includes(tab)) { bankState.sel = sel || null; activateTab(tab, { push: false }); }
  document.querySelector(".tabs").addEventListener("click", (ev) => {
    const b = ev.target.closest("[role=tab]");
    if (b) activateTab(b.dataset.tab);
  });
  // Arrow-key navigation between tabs
  document.querySelector(".tabs").addEventListener("keydown", (ev) => {
    if (!["ArrowLeft", "ArrowRight"].includes(ev.key)) return;
    const i = TABS.indexOf(bankState.tab) + (ev.key === "ArrowRight" ? 1 : -1);
    const t = TABS[(i + TABS.length) % TABS.length];
    activateTab(t);
    document.getElementById("tab-" + t).focus();
  });
}

// ------------------------------------------------------------------ formatting
const pct = (v, d = 2) => (v == null ? "—" : `${+v.toFixed(d)}%`);
const signed = (v, unit = " pp", d = 2) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(+v.toFixed(d))}${unit}`);
const STANCE = {
  tightening: { icon: "▲", label: "Tightening" },
  easing: { icon: "▼", label: "Easing" },
  holding: { icon: "■", label: "Holding" },
  unknown: { icon: "?", label: "Unknown" },
};
const OUTLOOK = { down: "Easing", up: "Rising", stable: "Stable" };
const stanceBadge = (b) => `<span class="stance st-${esc(b.stance)}"><span aria-hidden="true">${STANCE[b.stance].icon}</span> ${STANCE[b.stance].label}</span>`;
const targetText = (b) => (b.band ? `${b.band[0]}–${b.band[1]}%` : `${b.target}%`);

// ------------------------------------------------------------------ load
async function initBanks() {
  try {
    bankState.list = await fetch("data/central_banks.json", { cache: "no-cache" }).then((r) => r.json());
  } catch {
    document.getElementById("bank-cards").innerHTML = `<div class="empty">Central bank data not available yet.</div>`;
    return;
  }
  const L = bankState.list;
  const share = L.reduce((s, b) => s + (b.world_gdp_share || 0), 0);
  document.getElementById("banks-share").textContent = share.toFixed(0) + "%";
  const latest = L.map((b) => b.rate_period).filter(Boolean).sort().pop();
  document.getElementById("banks-asof").textContent = latest ? `Policy rates as of ${fmtDate(latest)} · source: BIS` : "";

  renderBankCards();
  initBankTable();
  renderEnergyPanel();
  if (!bankState.sel || !L.some((b) => b.area === bankState.sel)) bankState.sel = L[0]?.area;
  renderBankDetail();

  document.addEventListener("click", (ev) => {
    const card = ev.target.closest("[data-bank]");
    if (card) { selectBank(card.dataset.bank, true); return; }
    const link = ev.target.closest("[data-bank-link]");
    if (link) {
      ev.preventDefault();
      document.getElementById("detail").close();
      activateTab("banks");
      selectBank(link.dataset.bankLink, true);
    }
  });
}

function selectBank(area, scroll) {
  bankState.sel = area;
  renderBankCards();
  renderBankDetail();
  if (bankState.tab === "banks") history.replaceState(null, "", tabHash());
  if (scroll) document.getElementById("bank-detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

// Used by the country panel in app.js
function bankLinkFor(iso3) {
  const b = bankState.list.find((x) => x.countries.includes(iso3));
  if (!b) return "";
  return `<p class="bank-link">Central bank: <a href="#banks/${esc(b.area)}" data-bank-link="${esc(b.area)}">${esc(b.name)}</a>
    · policy rate ${pct(b.rate)} · ${STANCE[b.stance].label.toLowerCase()}</p>`;
}

// ------------------------------------------------------------------ cards
function renderBankCards() {
  document.getElementById("bank-cards").innerHTML = bankState.list.map((b) => `
    <button class="bank-card${b.area === bankState.sel ? " on" : ""}" data-bank="${esc(b.area)}" aria-pressed="${b.area === bankState.sel}">
      <span class="bc-top"><span class="bc-flag">${esc(b.flag)}</span><span class="bc-short">${esc(b.short)}</span>
        <span class="bc-share">${b.world_gdp_share.toFixed(1)}% of world GDP</span></span>
      <span class="bc-rate">${pct(b.rate)}</span>
      <span class="bc-meta">Inflation ${pct(b.cpi, 1)} · target ${esc(targetText(b))}</span>
      ${b.outlook ? verdictBadge(b.outlook) : stanceBadge(b)}
    </button>`).join("");
}

// ------------------------------------------------------------------ table
function initBankTable() {
  document.querySelectorAll("#bank-tbl th").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.k;
    bankState.sort = { k, asc: bankState.sort.k === k ? !bankState.sort.asc : k === "short" || k === "position" };
    renderBankTable();
  }));
  document.querySelector("#bank-tbl tbody").addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr[data-area]");
    if (tr) selectBank(tr.dataset.area, true);
  });
  renderBankTable();
}

function renderBankTable() {
  const { k, asc } = bankState.sort;
  const val = (b) => ({
    outlook: () => ({ down: -1, stable: 0, up: 1 }[b.inflation.direction]),
    verdict: () => ({ up: 1, hold: 0, down: -1 }[b.outlook?.lean]),
  }[k] || (() => b[k]))();
  const rows = bankState.list.slice().sort((a, b) => {
    const va = val(a), vb = val(b);
    if (va == null) return 1;
    if (vb == null) return -1;
    const r = typeof va === "string" ? va.localeCompare(vb) : va - vb;
    return asc ? r : -r;
  });
  document.querySelectorAll("#bank-tbl th").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.k === k);
    th.classList.toggle("asc", th.dataset.k === k && asc);
  });
  document.querySelector("#bank-tbl tbody").innerHTML = rows.map((b) => `
    <tr data-area="${esc(b.area)}">
      <td><span class="flag">${esc(b.flag)}</span>${esc(b.short)} <span class="muted">${esc(b.currency)}</span></td>
      <td class="num">${b.world_gdp_share.toFixed(1)}%</td>
      <td class="num">${pct(b.rate)}</td>
      <td class="num">${signed(b.rate_change_12m)}</td>
      <td class="num">${pct(b.cpi, 1)}</td>
      <td class="num">${esc(targetText(b))}</td>
      <td class="num">${signed(b.real_rate, "%", 1)}</td>
      <td>${b.outlook ? verdictBadge(b.outlook) : "—"}</td>
      <td class="num">${b.area === "US" ? "USD " : ""}${signed(b.currency_strength_12m, "%", 1)}</td>
      <td><span class="outlook o-${esc(b.inflation.direction)}"><span aria-hidden="true">${esc(b.inflation.arrow)}</span> ${OUTLOOK[b.inflation.direction]}</span></td>
    </tr>`).join("");
}

// Budget balance per year as small labelled bars (negative = deficit).
function fiscalBars(f) {
  const y = new Date().getFullYear();
  const items = [[y - 1, f.balance_prev], [y, f.balance], [y + 1, f.balance_next]].filter(([, v]) => v != null);
  const max = Math.max(1, ...items.map(([, v]) => Math.abs(v)));
  return items.map(([yr, v]) => `
    <div class="mb-row"><span class="mb-y">${yr}${yr > y ? " (plan)" : ""}</span>
      <span class="mb-track"><span class="mb-bar ${v < 0 ? "neg" : "pos"}" style="width:${(Math.abs(v) / max) * 100}%"></span></span>
      <span class="mb-v">${signed(v, "%", 1)}</span></div>`).join("");
}

// ------------------------------------------------------------------ detail
const LEAN = { up: { icon: "▲", cls: "lean-up" }, down: { icon: "▼", cls: "lean-down" }, hold: { icon: "■", cls: "lean-hold" } };
const verdictBadge = (o) => `<span class="verdict ${LEAN[o.lean].cls}"><span aria-hidden="true">${LEAN[o.lean].icon}</span> ${esc(o.verdict)}</span>`;
const TRIG_STATUS = { hike: "Hike trigger hit", cut: "Cut trigger hit", near: "Close to a trigger" };

function reasonList(title, items, cls) {
  if (!items.length) return "";
  return `<div class="rs ${cls}"><h4>${title}</h4><ul>${items.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>`;
}

function renderBankDetail() {
  const b = bankState.list.find((x) => x.area === bankState.sel);
  const box = document.getElementById("bank-detail");
  if (!b) { box.hidden = true; return; }
  box.hidden = false;
  const o = b.outlook;
  box.innerHTML = `
    <div class="bd-head">
      <span class="bd-flag">${esc(b.flag)}</span>
      <div><h2>${esc(b.name)} <span class="muted">(${esc(b.short)})</span></h2>
        <div class="muted">${esc(b.mandate)} · <a href="${esc(b.url)}" target="_blank" rel="noopener">official site</a></div></div>
    </div>
    <div class="bd-stats">
      <div><span class="l">Policy rate (${fmtDate(b.rate_period)})</span><span class="v">${pct(b.rate)}</span></div>
      <div><span class="l">Change in 12 months</span><span class="v">${signed(b.rate_change_12m)} ${stanceBadge(b)}</span></div>
      <div><span class="l">Inflation vs target</span><span class="v">${pct(b.cpi, 1)} <span class="muted">target ${esc(targetText(b))}</span></span></div>
      <div><span class="l">Real rate (rate − inflation)</span><span class="v">${signed(b.real_rate, "%", 1)} <span class="muted">${esc(b.position)}</span></span></div>
    </div>

    <div class="card outlook-card">
      <h3>Rate outlook ${verdictBadge(o)}</h3>
      <div class="reasons">
        ${reasonList("Why it may hold", o.hold, "rs-hold")}
        ${reasonList("Pressure to raise rates", o.hike, "rs-up")}
        ${reasonList("Room to cut rates", o.cut, "rs-down")}
      </div>
      <p class="muted small">Rule-based reading of the latest data, not a forecast. Central banks also weigh things not modelled here (wage deals, credit conditions, politics).</p>
    </div>

    <div class="card">
      <h3>What could make it move fast</h3>
      <div class="table-scroll"><table class="trig">
        <thead><tr><th>Variable</th><th>Now</th><th>Would push a <strong>hike</strong> if…</th><th>Would push a <strong>cut</strong> if…</th></tr></thead>
        <tbody>${o.triggers.map((t) => `<tr class="${t.status ? "ts-" + esc(t.status) : ""}">
          <td><strong>${esc(t.variable)}</strong>${t.status ? `<br><span class="tstat">${esc(TRIG_STATUS[t.status])}</span>` : ""}</td>
          <td class="num">${esc(t.now)}</td><td>${esc(t.hike)}</td><td>${esc(t.cut)}</td></tr>`).join("")}</tbody>
      </table></div>
    </div>

    <div class="card"><h3>Policy rate vs inflation</h3><div class="legend" id="lg-rates"></div><div id="ch-rates" class="chart"></div></div>

    <details class="more">
      <summary>More detail: currency, government budget, energy and inflation outlook</summary>
      <div class="bd-charts">
        <div class="card"><h3>Currency (${esc(b.currency)})</h3><p>${esc(b.currency_text)}</p>
          <h3 id="ch-fx-title" class="sub3"></h3><div class="legend" id="lg-fx"></div><div id="ch-fx" class="chart"></div></div>
        <div class="card"><h3>Inflation outlook <span class="outlook o-${esc(b.inflation.direction)}"><span aria-hidden="true">${esc(b.inflation.arrow)}</span> ${OUTLOOK[b.inflation.direction]}</span></h3>
          <p>${esc(b.inflation.text)}</p></div>
        <div class="card"><h3>Government budget ${b.fiscal ? `<span class="stance fs-${esc(b.fiscal.stance)}">${esc(b.fiscal.stance)}</span>` : ""}</h3>
          ${b.fiscal ? `<p>${esc(b.fiscal.text)}</p><div class="mini-bars" aria-label="Budget balance by year">${fiscalBars(b.fiscal)}</div>
            <p class="muted small">Source: ${esc(b.fiscal.source || "")}.</p>` : `<p class="muted">No fiscal data available.</p>`}</div>
        <div class="card"><h3>Energy ${b.energy && b.energy.shock !== "none" ? `<span class="stance en-${esc(b.energy.shock)}">oil ${signed(b.energy.oil_change_12m, "%", 0)}</span>` : ""}</h3>
          ${b.energy ? `<p>${esc(b.energy.text)}</p>` : `<p class="muted">No energy data available.</p>`}</div>
        <div class="card" id="bank-tariffs" hidden><h3>US tariffs and trade exposure</h3><div id="bank-tariffs-body"></div></div>
      </div>
    </details>`;
  // Tariff note comes from trade.js (Trade tab); filled when the section is opened, so trade data has loaded.
  const fillTariffs = () => {
    const html = typeof tariffNoteFor === "function" ? tariffNoteFor(b.countries) : "";
    const card = document.getElementById("bank-tariffs");
    if (!card) return;
    document.getElementById("bank-tariffs-body").innerHTML = html;
    card.hidden = !html;
  };
  box.querySelector("details.more").addEventListener("toggle", (ev) => { if (ev.target.open) fillTariffs(); });
  drawRateChart(b);
  drawFxChart(b);
}

// ------------------------------------------------------------------ line charts
const parseP = (p) => { const [y, mo] = p.split("-").map(Number); return new Date(Date.UTC(y, mo - 1, 1)); };

function lineChart(el, series, { band = null, refLine = null, yFmt = (v) => v.toFixed(1) + "%", yLabel = "" } = {}) {
  const box = document.getElementById(el);
  const W = 520, H = 220, m = { l: 40, r: 64, t: 10, b: 24 };
  const all = series.flatMap((s) => s.points);
  if (!all.length) { box.innerHTML = `<div class="empty">No data.</div>`; return; }
  const x = d3.scaleUtc().domain(d3.extent(all, (p) => parseP(p[0]))).range([m.l, W - m.r]);
  const vals = all.map((p) => p[1]).concat(band || [], refLine != null ? [refLine] : []);
  const y = d3.scaleLinear().domain(d3.extent(vals)).nice(5).range([H - m.b, m.t]);
  const svg = d3.select(box).html("").append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
    .attr("aria-label", series.map((s) => `${s.name}: latest ${yFmt(s.points.at(-1)[1])}`).join("; "));

  svg.append("g").attr("class", "grid").selectAll("line").data(y.ticks(5)).join("line")
    .attr("x1", m.l).attr("x2", W - m.r).attr("y1", y).attr("y2", y);
  svg.append("g").attr("class", "yax").selectAll("text").data(y.ticks(5)).join("text")
    .attr("x", m.l - 6).attr("y", (v) => y(v) + 4).attr("text-anchor", "end").text(yFmt);
  svg.append("g").attr("class", "xax").selectAll("text").data(x.ticks(5)).join("text")
    .attr("x", x).attr("y", H - 6).attr("text-anchor", "middle")
    .text((d) => d.toLocaleString("en", { month: "short", year: "2-digit", timeZone: "UTC" }));
  if (band) {
    svg.append("rect").attr("class", "band").attr("x", m.l).attr("width", W - m.r - m.l)
      .attr("y", y(band[1])).attr("height", Math.max(1, y(band[0]) - y(band[1])));
    svg.append("text").attr("class", "band-l").attr("x", W - m.r + 4).attr("y", y((band[0] + band[1]) / 2) + 4).text("target");
  }
  if (refLine != null) {
    svg.append("line").attr("class", "ref").attr("x1", m.l).attr("x2", W - m.r).attr("y1", y(refLine)).attr("y2", y(refLine));
    if (!band) svg.append("text").attr("class", "band-l").attr("x", W - m.r + 4).attr("y", y(refLine) + 4).text(yLabel || "target");
  }
  const ln = d3.line().x((p) => x(parseP(p[0]))).y((p) => y(p[1]));
  series.forEach((s) => {
    svg.append("path").attr("class", "series").attr("stroke", s.color).attr("d", ln(s.points))
      .attr("stroke-dasharray", s.dashed ? "5 4" : null);
    const last = s.points.at(-1);
    svg.append("text").attr("class", "dlabel").attr("x", x(parseP(last[0])) + 6).attr("y", y(last[1]) + 4).text(yFmt(last[1]));
  });

  // Hover: crosshair + tooltip with every series at that month
  const months = [...new Set(all.map((p) => p[0]))].sort();
  const cross = svg.append("line").attr("class", "cross").attr("y1", m.t).attr("y2", H - m.b).style("display", "none");
  const dots = series.map((s) => svg.append("circle").attr("r", 4).attr("fill", s.color).attr("class", "hdot").style("display", "none"));
  const tip = document.getElementById("tip");
  svg.append("rect").attr("x", m.l).attr("y", m.t).attr("width", W - m.r - m.l).attr("height", H - m.t - m.b)
    .attr("fill", "transparent")
    .on("mousemove", (ev) => {
      const [mx] = d3.pointer(ev);
      const t = x.invert(mx);
      const p = months.reduce((a, b) => (Math.abs(parseP(b) - t) < Math.abs(parseP(a) - t) ? b : a));
      cross.style("display", null).attr("x1", x(parseP(p))).attr("x2", x(parseP(p)));
      const rows = series.map((s, i) => {
        const pt = s.points.find((q) => q[0] === p);
        dots[i].style("display", pt ? null : "none");
        if (pt) dots[i].attr("cx", x(parseP(p))).attr("cy", y(pt[1]));
        return pt ? `<div><span class="sw" style="background:${s.color}"></span>${esc(s.name)}: <strong>${esc(yFmt(pt[1]))}</strong></div>` : "";
      }).join("");
      tip.innerHTML = `<strong>${esc(fmtDate(p))}</strong>${rows}`;
      tip.hidden = false;
      tip.style.left = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8) + "px";
      tip.style.top = ev.clientY + 14 + "px";
    })
    .on("mouseleave", () => { tip.hidden = true; cross.style("display", "none"); dots.forEach((d) => d.style("display", "none")); });
}

const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

function legend(id, items) {
  document.getElementById(id).innerHTML = items.map(([name, color, dashed]) =>
    `<span><span class="sw${dashed ? " dashed" : ""}" style="background:${color}"></span>${esc(name)}</span>`).join("");
}

function drawRateChart(b) {
  const cRate = cssVar("--k-pres"), cCpi = cssVar("--k-leg");
  legend("lg-rates", [["Policy rate", cRate], ["Inflation (CPI, y/y)", cCpi], [`Target ${targetText(b)}`, cssVar("--surface-2")]]);
  lineChart("ch-rates", [
    { name: "Policy rate", color: cRate, points: b.history.rates },
    { name: "Inflation", color: cCpi, points: b.history.cpi },
  ], { band: b.band, refLine: b.band ? null : b.target });
}

// Currency strength index: 100 = 12 months before the latest month; above 100 = stronger vs USD.
function strengthIndex(fx, invert) {
  if (!fx.length) return [];
  const lastP = fx.at(-1)[0];
  const [y, mo] = lastP.split("-").map(Number);
  const baseP = `${y - 1}-${String(mo).padStart(2, "0")}`;
  const base = (fx.filter((p) => p[0] <= baseP).at(-1) || fx[0])[1];
  return fx.map(([p, v]) => [p, invert ? (v / base) * 100 : (base / v) * 100]);
}

function drawFxChart(b) {
  const color = cssVar("--k-pres");
  let pts, title, name;
  if (b.area === "US") {
    // Average of the other currencies' "local per USD" moves = dollar strength.
    const idx = bankState.list.filter((x) => x.area !== "US").map((x) => strengthIndex(x.history.fx, true));
    const months = [...new Set(idx.flatMap((s) => s.map((p) => p[0])))].sort();
    pts = months.map((p) => {
      const vs = idx.map((s) => s.find((q) => q[0] === p)?.[1]).filter((v) => v != null);
      return vs.length >= 6 ? [p, vs.reduce((a, c) => a + c, 0) / vs.length] : null;
    }).filter(Boolean);
    title = "US dollar vs the other 12 currencies"; name = "USD strength";
  } else {
    pts = strengthIndex(b.history.fx, false);
    title = `${b.currency} strength vs US dollar`; name = `${b.currency} vs USD`;
  }
  document.getElementById("ch-fx-title").textContent = title;
  legend("lg-fx", [[name + " (index, 100 = a year ago; higher = stronger)", color], ["100 line", cssVar("--muted"), true]]);
  lineChart("ch-fx", [{ name, color, points: pts }], { refLine: 100, yFmt: (v) => v.toFixed(0), yLabel: "a year ago" });
}

// ------------------------------------------------------------------ energy panel (top of the tab)
async function renderEnergyPanel() {
  let en;
  try { en = await fetch("data/energy.json", { cache: "no-cache" }).then((r) => r.json()); } catch { return; }
  if (!en || !en.brent || !en.brent.length) return;
  let box = document.getElementById("energy-panel");
  if (!box) {
    box = document.createElement("section");
    box.className = "panel";
    box.id = "energy-panel";
    document.getElementById("bank-detail").insertAdjacentElement("beforebegin", box);
  }
  const actual = en.brent.filter((p) => p[0] <= en.last_actual);
  const proj = en.brent.filter((p) => p[0] >= en.last_actual);
  const [pNow, now] = actual.at(-1);
  const ago = (actual.filter((p) => p[0] <= `${+pNow.slice(0, 4) - 1}${pNow.slice(4)}`).at(-1) || actual[0])[1];
  const ahead = proj.find((p) => p[0] === `${+pNow.slice(0, 4) + 1}${pNow.slice(4)}`) || proj.at(-1);
  const chg = (now / ago - 1) * 100;
  const fchg = ahead ? (ahead[1] / now - 1) * 100 : null;
  const shock = Math.abs(chg) >= 15;
  const importers = bankState.list.filter((b) => b.energy && b.energy.import_dependence > 10).map((b) => b.short);
  const exporters = bankState.list.filter((b) => b.energy && b.energy.import_dependence < -10).map((b) => b.short);
  box.innerHTML = `
    <div class="panel-head"><h2>Energy shock monitor</h2><span class="muted">Brent crude · EIA Short-Term Energy Outlook</span></div>
    <div class="bd-grid">
      <div>
        <div class="bd-stats">
          <div><span class="l">Brent oil (${fmtDate(pNow)})</span><span class="v">$${now.toFixed(0)}</span></div>
          <div><span class="l">Change over 12 months</span><span class="v">${signed(chg, "%", 0)} ${shock ? `<span class="stance en-${chg > 0 ? "up" : "down"}">${chg > 0 ? "price shock" : "price slump"}</span>` : ""}</span></div>
          ${ahead ? `<div><span class="l">EIA projection (${fmtDate(ahead[0])})</span><span class="v">$${ahead[1].toFixed(0)} <span class="muted">${signed(fchg, "%", 0)}</span></span></div>` : ""}
        </div>
        <p>${shock && chg > 0
          ? `Oil is ${chg.toFixed(0)}% dearer than a year ago. For energy <strong>importers</strong> (${esc(importers.join(", "))}) this is a negative supply shock: costs and inflation rise while real incomes fall (IS shifts left), so central banks face higher inflation <em>and</em> weaker growth. <strong>Exporters</strong> (${esc(exporters.join(", "))}) gain income (IS shifts right) and their currencies tend to strengthen.`
          : shock ? `Oil is ${Math.abs(chg).toFixed(0)}% cheaper than a year ago: a relief for importers (${esc(importers.join(", "))}) and an income loss for exporters (${esc(exporters.join(", "))}).`
          : "Oil prices are close to where they were a year ago, so energy is not a major driver of inflation right now."}
          ${fchg != null ? ` The EIA expects Brent ${fchg < -5 ? "to ease" : fchg > 5 ? "to rise further" : "to stay around this level"} over the next year${fchg < -5 && chg > 0 ? ", so the inflation impulse should fade" : ""}.` : ""}</p>
      </div>
      <div><div class="legend" id="lg-oil"></div><div id="ch-oil" class="chart"></div></div>
    </div>`;
  const c = cssVar("--k-leg");
  legend("lg-oil", [["Brent, $ per barrel", c], ["EIA projection", c, true]]);
  lineChart("ch-oil", [
    { name: "Brent", color: c, points: actual },
    { name: "EIA projection", color: c, points: proj, dashed: true },
  ], { yFmt: (v) => "$" + v.toFixed(0) });
}
