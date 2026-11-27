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
      ${stanceBadge(b)}
      <span class="bc-meta">Inflation ${pct(b.cpi, 1)} · target ${esc(targetText(b))}</span>
      <span class="bc-meta">Real rate ${signed(b.real_rate, "%", 1)} · ${esc(b.position)}</span>
    </button>`).join("");
}

// ------------------------------------------------------------------ table
function initBankTable() {
  // Fiscal + energy columns, inserted before "Inflation outlook" (keeps index.html unchanged).
  const outlookTh = document.querySelector('#bank-tbl th[data-k="outlook"]');
  if (outlookTh && !document.querySelector('#bank-tbl th[data-k="fiscal_balance"]')) {
    outlookTh.insertAdjacentHTML("beforebegin",
      `<th data-k="fiscal_balance" class="num">Budget ${new Date().getFullYear()} (% GDP)</th>` +
      `<th data-k="fiscal_impulse" class="num">Fiscal impulse</th>` +
      `<th data-k="energy_dep" class="num">Energy imports</th>`);
  }
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
    fiscal_balance: () => b.fiscal?.balance,
    fiscal_impulse: () => b.fiscal?.impulse,
    energy_dep: () => b.energy?.import_dependence,
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
      <td>${esc(b.position)}</td>
      <td class="num">${b.area === "US" ? "USD " : ""}${signed(b.currency_strength_12m, "%", 1)}</td>
      <td class="num">${b.fiscal ? signed(b.fiscal.balance, "%", 1) : "—"}</td>
      <td class="num">${b.fiscal ? signed(b.fiscal.impulse, " pp", 1) : "—"}</td>
      <td class="num">${b.energy && b.energy.import_dependence != null ? signed(b.energy.import_dependence, "%", 0) : "—"}</td>
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
function renderBankDetail() {
  const b = bankState.list.find((x) => x.area === bankState.sel);
  const box = document.getElementById("bank-detail");
  if (!b) { box.hidden = true; return; }
  box.hidden = false;
  const rateLine = `${pct(b.rate)} <span class="muted">(${fmtDate(b.rate_period)})</span>`;
  box.innerHTML = `
    <div class="bd-head">
      <span class="bd-flag">${esc(b.flag)}</span>
      <div><h2>${esc(b.name)} <span class="muted">(${esc(b.short)})</span></h2>
        <div class="muted">${esc(b.mandate)} · <a href="${esc(b.url)}" target="_blank" rel="noopener">official site</a></div></div>
    </div>
    <div class="bd-stats">
      <div><span class="l">Policy rate</span><span class="v">${rateLine}</span></div>
      <div><span class="l">12-month change</span><span class="v">${signed(b.rate_change_12m)} ${stanceBadge(b)}</span></div>
      <div><span class="l">Inflation (CPI)</span><span class="v">${pct(b.cpi, 1)} <span class="muted">target ${esc(targetText(b))}</span></span></div>
      <div><span class="l">Real rate</span><span class="v">${signed(b.real_rate, "%", 1)} <span class="muted">${esc(b.position)}</span></span></div>
      <div><span class="l">${b.area === "US" ? "Dollar vs others" : esc(b.currency) + " vs USD"} (12 mo)</span><span class="v">${signed(b.currency_strength_12m, "%", 1)}</span></div>
      ${b.fiscal ? `<div><span class="l">Budget balance ${new Date().getFullYear()}</span><span class="v">${signed(b.fiscal.balance, "% GDP", 1)} <span class="muted">${esc(b.fiscal.stance)}</span></span></div>` : ""}
      ${b.energy ? `<div><span class="l">Energy imports (net)</span><span class="v">${b.energy.import_dependence != null ? signed(b.energy.import_dependence, "%", 0) : "—"} <span class="muted">${esc(b.energy.role.replace("net energy ", ""))}</span></span></div>` : ""}
    </div>
    <div class="bd-grid">
      <div class="card">
        <h3>IS-LM: what this policy does</h3>
        <div id="islm"></div>
        <p class="caption" id="islm-caption"></p>
      </div>
      <div class="bd-text">
        <div class="card"><h3>Monetary policy</h3><p>${esc(STANCE[b.stance].label)}: ${esc(b.stance_note)}. ${esc(b.islm_text)}</p></div>
        <div class="card"><h3>Currency (${esc(b.currency)})</h3><p>${esc(b.currency_text)}</p></div>
        <div class="card"><h3>Inflation outlook <span class="outlook o-${esc(b.inflation.direction)}"><span aria-hidden="true">${esc(b.inflation.arrow)}</span> ${OUTLOOK[b.inflation.direction]}</span></h3>
          <p>${esc(b.inflation.text)}</p><p class="muted small">Rule-based estimate, not a forecast.</p></div>
      </div>
    </div>
    <div class="bd-charts">
      <div class="card"><h3>Fiscal policy ${b.fiscal ? `<span class="stance fs-${esc(b.fiscal.stance)}">${esc(b.fiscal.stance)}</span>` : ""}</h3>
        ${b.fiscal ? `<p>${esc(b.fiscal.text)}</p>
          <div class="mini-bars" aria-label="Budget balance by year">${fiscalBars(b.fiscal)}</div>
          <p class="muted small">Source: ${esc(b.fiscal.source || "")}. Impulse = rise in the deficit this year; positive = stimulus.</p>`
        : `<p class="muted">No fiscal data available.</p>`}</div>
      <div class="card"><h3>Energy shock ${b.energy && b.energy.shock !== "none" ? `<span class="stance en-${esc(b.energy.shock)}">oil ${signed(b.energy.oil_change_12m, "%", 0)}</span>` : ""}</h3>
        ${b.energy ? `<p>${esc(b.energy.text)}</p><p class="muted small">Oil: EIA Short-Term Energy Outlook. Import dependence: World Bank. Pass-through rule: +10% oil ≈ +0.3 pp inflation.</p>`
        : `<p class="muted">No energy data available.</p>`}</div>
    </div>
    <div class="bd-charts">
      <div class="card"><h3>Policy rate vs inflation</h3><div class="legend" id="lg-rates"></div><div id="ch-rates" class="chart"></div></div>
      <div class="card"><h3 id="ch-fx-title"></h3><div class="legend" id="lg-fx"></div><div id="ch-fx" class="chart"></div></div>
    </div>`;
  drawISLM(b);
  drawRateChart(b);
  drawFxChart(b);
}

// ------------------------------------------------------------------ IS-LM diagram
function drawISLM(b) {
  const W = 420, H = 300, m = { l: 44, r: 20, t: 14, b: 40 };
  const w = W - m.l - m.r, h = H - m.t - m.b;
  // Schematic in unit space:  IS: r = 0.95 - 0.9Y + a     LM: r = 0.05 + 0.9Y + s
  const d = b.lm_shift || 0, di = b.is_shift || 0;
  const lmMoved = Math.abs(d) >= 0.01, isMoved = Math.abs(di) >= 0.3;
  const clamp = (v, lo) => Math.max(-0.26, Math.min(0.26, v)) || 0;
  let s1 = clamp(d * 0.12);
  if (lmMoved && Math.abs(s1) < 0.06) s1 = Math.sign(d) * 0.06;
  let a1 = clamp(di * 0.06);
  if (isMoved && Math.abs(a1) < 0.06) a1 = Math.sign(di) * 0.06;
  if (!isMoved) a1 = 0;
  const moved = lmMoved || isMoved;
  const eq = (s, a) => { const Y = (0.9 + a - s) / 1.8; return [Y, 0.95 - 0.9 * Y + a]; };
  const X = (Y) => m.l + Y * w, R = (r) => m.t + (1 - r) * h;
  const line = (f) => { const pts = []; for (let Y = 0.04; Y <= 0.96; Y += 0.02) pts.push([X(Y), R(f(Y))]); return "M" + pts.map((p) => p.join(",")).join("L"); };
  const ISf = (a) => (Y) => 0.95 - 0.9 * Y + a, LMf = (s) => (Y) => 0.05 + 0.9 * Y + s;
  const [Y0, r0] = eq(0, 0), [Y1, r1] = eq(s1, a1);

  // Label at the visible end of an LM line (upward), or the low end of an IS line (downward).
  const lmLabel = (text, s, side, cls) => {
    let Y = 0.9;
    if (0.05 + 0.9 * Y + s > 0.97) Y = (0.97 - 0.05 - s) / 0.9;
    const r = 0.05 + 0.9 * Y + s;
    return `<text class="lbl ${cls}" x="${X(Y) + (side === "above" ? -30 : 6)}" y="${R(r) + (side === "above" ? -6 : 16)}">${text}</text>`;
  };
  const isLabel = (text, a, side, cls) => {
    let Y = 0.9;
    if (0.95 - 0.9 * Y + a < 0.03) Y = (0.95 + a - 0.03) / 0.9;
    const r = 0.95 - 0.9 * Y + a;
    return `<text class="lbl ${cls}" x="${X(Y) + (side === "above" ? 4 : -30)}" y="${R(r) + (side === "above" ? -8 : 18)}">${text}</text>`;
  };
  const arrow = (x1, y1, x2, y2) => {
    const ang = Math.atan2(y2 - y1, x2 - x1), hx = x2 - 9 * Math.cos(ang), hy = y2 - 9 * Math.sin(ang);
    const px = 5 * Math.sin(ang), py = -5 * Math.cos(ang);
    return `<line class="shift" x1="${x1}" y1="${y1}" x2="${hx}" y2="${hy}"/>
      <path class="islm-arrowhead" d="M${x2},${y2} L${hx + px},${hy + py} L${hx - px},${hy - py} Z"/>`;
  };
  // LM arrow: horizontal at r of LM0(0.66); IS arrow: horizontal at r of IS0(0.3)
  // Arrows sit away from the equilibria: LM arrow upper right, IS arrow lower right.
  const lmA = s1 > 0 ? 0.8 : 0.72, isA = a1 > 0 ? 0.74 : 0.82;
  const lmArrow = lmMoved ? arrow(X(lmA) + (s1 > 0 ? -3 : 3), R(LMf(0)(lmA)), X(lmA - s1 / 0.9) + (s1 > 0 ? 3 : -3), R(LMf(0)(lmA))) : "";
  const isArrow = isMoved ? arrow(X(isA) + (a1 > 0 ? 3 : -3), R(ISf(0)(isA)), X(isA + a1 / 0.9) + (a1 > 0 ? -3 : 3), R(ISf(0)(isA))) : "";
  const rClose = Math.abs(R(r1) - R(r0)) < 13, yClose = Math.abs(X(Y1) - X(Y0)) < 22;

  const desc = [
    lmMoved ? (d > 0 ? "LM shifts up/left (monetary tightening)" : "LM shifts down/right (monetary easing)") : "LM unchanged",
    isMoved ? (di > 0 ? "IS shifts right (fiscal stimulus / energy gain)" : "IS shifts left (fiscal squeeze / energy shock)") : "IS unchanged",
  ].join("; ");
  const svg = `
  <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="IS-LM diagram: ${esc(desc)}">
    <defs><clipPath id="plot"><rect x="${m.l}" y="${m.t}" width="${w}" height="${h}"/></clipPath></defs>
    <line class="axis" x1="${m.l}" y1="${m.t}" x2="${m.l}" y2="${m.t + h}"/>
    <line class="axis" x1="${m.l}" y1="${m.t + h}" x2="${m.l + w}" y2="${m.t + h}"/>
    <text class="ax-l" x="${m.l + w}" y="${H - 10}" text-anchor="end">Output (Y)</text>
    <text class="ax-l" transform="translate(14 ${m.t + h / 2}) rotate(-90)" text-anchor="middle">Interest rate (r)</text>
    <g clip-path="url(#plot)">
      <path class="is ${isMoved ? "lm0" : ""}" d="${line(ISf(0))}"/>
      ${isMoved ? `<path class="is" d="${line(ISf(a1))}"/>` : ""}
      <path class="lm ${lmMoved ? "lm0" : ""}" d="${line(LMf(0))}"/>
      ${lmMoved ? `<path class="lm" d="${line(LMf(s1))}"/>` : ""}
    </g>
    ${isLabel(isMoved ? "IS₀" : "IS", 0, isMoved && a1 > 0 ? "below" : "above", isMoved ? "dim" : "")}
    ${isMoved ? isLabel("IS₁", a1, a1 > 0 ? "above" : "below", "") : ""}
    ${lmLabel(lmMoved ? "LM₀" : "LM", 0, lmMoved ? (s1 > 0 ? "below" : "above") : "below", lmMoved ? "dim" : "")}
    ${lmMoved ? lmLabel("LM₁", s1, s1 > 0 ? "above" : "below", "") : ""}
    ${guide(X(Y0), R(r0), m, h, moved ? "dim" : "")}
    ${moved ? guide(X(Y1), R(r1), m, h, "") : ""}
    <circle class="eq ${moved ? "eq0" : ""}" cx="${X(Y0)}" cy="${R(r0)}" r="5"/>
    ${moved ? `<circle class="eq" cx="${X(Y1)}" cy="${R(r1)}" r="5"/>` : ""}
    ${lmArrow}${isArrow}
    <text class="lbl small" x="${X(Y0) + 8}" y="${R(r0) + (moved && r1 > r0 ? 16 : -8)}">${moved ? "E₀" : "E"}</text>
    ${moved ? `<text class="lbl small" x="${X(Y1) + 8}" y="${R(r1) + (r1 > r0 ? -8 : 16)}">E₁</text>` : ""}
    <text class="tick" x="${m.l - 6}" y="${R(r0) + 4}" text-anchor="end">${!moved ? "r" : rClose ? "r₀≈r₁" : "r₀"}</text>
    ${moved && !rClose ? `<text class="tick" x="${m.l - 6}" y="${R(r1) + 4}" text-anchor="end">r₁</text>` : ""}
    <text class="tick" x="${X(Y0) + (moved && yClose ? (Y0 > Y1 ? 6 : -6) : 0)}" y="${m.t + h + 14}" text-anchor="${moved && yClose ? (Y0 > Y1 ? "start" : "end") : "middle"}">${moved ? "Y₀" : "Y"}</text>
    ${moved ? `<text class="tick" x="${X(Y1) + (yClose ? (Y1 > Y0 ? 6 : -6) : 0)}" y="${m.t + h + 14}" text-anchor="${yClose ? (Y1 > Y0 ? "start" : "end") : "middle"}">Y₁</text>` : ""}
  </svg>`;
  document.getElementById("islm").innerHTML = svg;

  const parts = [];
  if (lmMoved) parts.push(`Monetary: rate ${signed(d)} over 12 months → LM ${d > 0 ? "up/left" : "down/right"}.`);
  else parts.push("Monetary: rate unchanged → LM stays put.");
  if (isMoved) {
    const why = [];
    if (b.fiscal && Math.abs(b.fiscal.impulse) >= 0.3) why.push(`fiscal impulse ${signed(b.fiscal.impulse, " pp of GDP", 1)}`);
    if (b.energy && Math.abs(b.energy.is_effect * 4) >= 0.3) why.push(`oil ${signed(b.energy.oil_change_12m, "%", 0)} for a ${b.energy.role}`);
    parts.push(`Fiscal + energy: ${why.join(" and ") || "combined push"} → IS ${di > 0 ? "right" : "left"}.`);
  } else parts.push("Fiscal + energy: small net effect → IS roughly unchanged.");
  if (moved) {
    const rWord = r1 > r0 + 0.005 ? "rises" : r1 < r0 - 0.005 ? "falls" : "is roughly unchanged";
    const yWord = Y1 > Y0 + 0.005 ? "rises" : Y1 < Y0 - 0.005 ? "falls" : "is roughly unchanged";
    parts.push(`Net result (E₀ → E₁): interest rate ${rWord}, output ${yWord}.`);
  }
  parts.push("Schematic, not to scale.");
  document.getElementById("islm-caption").textContent = parts.join(" ");
}

function guide(x, y, m, h, cls) {
  return `<line class="guide ${cls}" x1="${m.l}" y1="${y}" x2="${x}" y2="${y}"/><line class="guide ${cls}" x1="${x}" y1="${y}" x2="${x}" y2="${m.t + h}"/>`;
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
