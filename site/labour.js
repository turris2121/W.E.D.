"use strict";
/* Labour tab: ILO harmonised unemployment (one definition for all), national figures,
   definition/method changes, hidden unemployment, participation and minimum wages.
   Uses esc, compact, $ from app.js; setTabSub from tabs.js; d3 from CDN. */

const lbState = { data: null, sort: { k: "rank", asc: true }, sel: null, evFilter: "all", evShow: 30 };
const lbPct = (v, d = 1) => (v == null ? "—" : `${(+v).toFixed(d)}%`);
const lbPp = (v, d = 1) => (v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(d)} pp`);
const lbMoney = (v) => (v == null ? "—" : "$" + Math.round(v).toLocaleString("en"));
const EV_TYPES = {
  redefinition: { label: "Redefinition", group: "redefinition" },
  suspension: { label: "Suspended / questioned", group: "redefinition" },
  "survey change": { label: "Survey change", group: "survey" },
  coverage: { label: "Coverage", group: "survey" },
  "two measures": { label: "Two measures", group: "survey" },
  "break in series": { label: "Break in series", group: "break" },
  "data gap": { label: "Data gap", group: "break" },
};
const gradeBadge = (g) => `<span class="grade gr-${esc(g)}">${esc(g)}</span>`;

async function initLabour() {
  try {
    lbState.data = await fetch("data/labour.json", { cache: "no-cache" }).then((r) => r.json());
  } catch {
    document.getElementById("lb-events").innerHTML = `<div class="empty">Labour data not available yet.</div>`;
    return;
  }
  const C = lbState.data.countries;
  C.forEach((c, i) => { c._rank = c.gdp_rank || 900 + i; c._changes = recentChanges(c).length; });

  renderLbKpis();
  renderLbEvents();
  renderDumbbell();
  initLbTable();

  document.getElementById("lb-ev-filter").addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-f]");
    if (!b) return;
    lbState.evFilter = b.dataset.f;
    lbState.evShow = 30;
    document.querySelectorAll("#lb-ev-filter button").forEach((x) => x.classList.toggle("on", x === b));
    renderLbEvents();
  });
  document.getElementById("pane-labour").addEventListener("click", (ev) => {
    const more = ev.target.closest("[data-lb-more]");
    if (more) { lbState.evShow += 40; renderLbEvents(); return; }
    const el = ev.target.closest("[data-lb]");
    if (el) selectLabour(el.dataset.lb, true);
  });
  // Deep link: #labour/NGA
  const openSub = (sub) => { if (sub && C.some((c) => c.iso3 === sub)) selectLabour(sub, false); };
  document.addEventListener("tabshow", (ev) => { if (ev.detail.name === "labour") openSub(ev.detail.sub); });
  const [tab, sub] = location.hash.slice(1).split("/");
  if (tab === "labour") openSub(sub);
}

function recentChanges(c) {
  const y = new Date().getFullYear();
  return c.events.filter((e) => (e.year || 0) >= y - 10 &&
    ["redefinition", "suspension", "survey change", "coverage", "break in series"].includes(e.type));
}

// ------------------------------------------------------------------ KPIs
function renderLbKpis() {
  const d = lbState.data, C = d.countries, y = new Date().getFullYear();
  const low = C.filter((c) => c.grade === "Low").length;
  const changed5 = C.filter((c) => c.events.some((e) => (e.year || 0) >= y - 5 &&
    ["redefinition", "suspension", "survey change", "coverage", "break in series"].includes(e.type))).length;
  const hidden = C.filter((c) => c.lu4 != null && c.national != null && c.lu4 >= 2 * c.national).length;
  const tiles = [
    [d.world.rate != null ? lbPct(d.world.rate) : "—", `World unemployment, ILO harmonised (${d.world.year})`],
    [low, "countries with Low comparability"],
    [changed5, "countries that changed definition, survey or coverage in the last 5 years"],
    [hidden, "countries where the broad measure (LU4) is at least double the headline"],
  ];
  document.getElementById("lb-kpis").innerHTML = tiles.map(([v, l]) =>
    `<div class="kpi"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
}

// ------------------------------------------------------------------ watchlist
function renderLbEvents() {
  const f = lbState.evFilter;
  const all = [];
  for (const c of lbState.data.countries) for (const e of c.events) {
    if (f !== "all" && (EV_TYPES[e.type]?.group || "survey") !== f) continue;
    all.push({ ...e, c });
  }
  // Hand-checked notes first within a year; undated "two measures" notes go to the end.
  all.sort((a, b) => (b.year || 0) - (a.year || 0) || (a.auto - b.auto) || (a.c._rank - b.c._rank));
  const shown = all.slice(0, lbState.evShow);
  document.getElementById("lb-events").innerHTML = shown.map((e) => `
    <button class="lb-ev ${e.auto ? "" : "curated"}" data-lb="${esc(e.c.iso3)}">
      <span class="lb-ev-y">${e.year ?? "ongoing"}</span>
      <span class="lb-ev-body">
        <span class="lb-ev-t"><span class="flag">${esc(e.c.flag || "")}</span> <strong>${esc(e.c.name)}</strong> · ${esc(e.title)}
          <span class="evtype et-${esc((EV_TYPES[e.type]?.group) || "survey")}">${esc(EV_TYPES[e.type]?.label || e.type)}</span>
          ${e.auto ? '<span class="taga">auto</span>' : '<span class="tagc">hand-checked</span>'}</span>
        <span class="lb-ev-d">${esc(e.detail)}</span>
      </span>
    </button>`).join("") +
    (all.length > shown.length ? `<button class="lb-more" data-lb-more>Show more (${all.length - shown.length} left)</button>` : "") +
    (all.length ? "" : `<div class="empty">No changes of this kind.</div>`);
}

// ------------------------------------------------------------------ dumbbell
function renderDumbbell() {
  // Headline (ILO harmonised) vs broad unemployment (LU4) for the largest economies; national survey for reference.
  const rows = lbState.data.countries.filter((c) => c.gdp_rank && c.gdp_rank <= 30).sort((a, b) => a.gdp_rank - b.gdp_rank);
  const box = document.getElementById("lb-dumbbell");
  if (!rows.length) { box.innerHTML = `<div class="empty">No data.</div>`; return; }
  const W = 780, rowH = 22, m = { l: 190, r: 96, t: 24, b: 10 };
  const H = m.t + rows.length * rowH + m.b;
  const max = Math.ceil(d3.max(rows, (c) => Math.max(c.national || 0, c.harmonised, c.lu4 || 0)) / 5) * 5;
  const x = d3.scaleLinear().domain([0, max]).range([m.l, W - m.r]);
  const cNat = cssVar("--k-leg"), cHar = cssVar("--k-pres"), cLu = cssVar("--text-2");
  const short = (n) => (n.length > 24 ? n.replace(/^People's Republic of /, "").replace(/^Kingdom of the /, "").slice(0, 24) : n);
  const ticks = x.ticks(6);
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Headline vs broad unemployment for the largest economies">
    ${ticks.map((t) => `<line class="gridl" x1="${x(t)}" x2="${x(t)}" y1="${m.t - 6}" y2="${H - m.b}"/>
      <text class="axt" x="${x(t)}" y="${m.t - 10}" text-anchor="middle">${t}%</text>`).join("")}
    <text class="axt" x="${W - m.r + 24}" y="${m.t - 10}">hidden</text>
    ${rows.map((c, i) => {
      const y = m.t + i * rowH + rowH / 2;
      const lu = c.lu4 != null && c.lu4_year && c.lu4_year >= lbState.data.estimate_year - 3 ? c.lu4 : null;
      const hid = lu != null ? lu - c.harmonised : null;
      return `<g class="db-row" data-lb="${esc(c.iso3)}" tabindex="0">
        <rect x="0" y="${y - rowH / 2}" width="${W}" height="${rowH}" class="db-hit" fill="#000" fill-opacity="0"/>
        <text class="db-l" x="${m.l - 10}" y="${y + 4}" text-anchor="end">${esc((c.flag || "") + " " + short(c.name))}</text>
        ${lu != null ? `<line class="db-line ${hid >= 5 ? "big" : ""}" x1="${x(c.harmonised)}" x2="${x(lu)}" y1="${y}" y2="${y}"/>
          <rect x="${x(lu) - 2}" y="${y - 7}" width="4" height="14" rx="1" fill="${cLu}" class="db-dot"><title>${esc(c.name)} broad unemployment LU4 ${c.lu4_year}: ${lbPct(lu)}</title></rect>` : ""}
        ${c.national != null ? `<circle cx="${x(c.national)}" cy="${y}" r="4.5" fill="${cNat}" class="db-dot"><title>${esc(c.name)} national survey ${c.national_year}: ${lbPct(c.national)}</title></circle>` : ""}
        <path d="M${x(c.harmonised)},${y - 6} l6,6 l-6,6 l-6,-6 z" fill="${cHar}" class="db-dot"><title>${esc(c.name)} ILO harmonised ${c.harmonised_year}: ${lbPct(c.harmonised)}</title></path>
        <text class="db-v" x="${W - m.r + 8}" y="${y + 4}">${hid != null ? "+" + hid.toFixed(1) + " pp" : "no LU4"}</text>
      </g>`;
    }).join("")}
  </svg>`;
}

// ------------------------------------------------------------------ table
function initLbTable() {
  const regions = [...new Set(lbState.data.countries.map((c) => c.region).filter(Boolean))].sort();
  document.getElementById("lb-region").insertAdjacentHTML("beforeend", regions.map((r) => `<option>${esc(r)}</option>`).join(""));
  ["lb-q", "lb-region", "lb-grade"].forEach((id) => document.getElementById(id).addEventListener("input", renderLbTable));
  document.querySelectorAll("#lb-tbl th").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.k;
    lbState.sort = { k, asc: lbState.sort.k === k ? !lbState.sort.asc : ["name", "grade"].includes(k) };
    renderLbTable();
  }));
  document.querySelector("#lb-tbl tbody").addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr[data-iso]");
    if (tr) selectLabour(tr.dataset.iso, true);
  });
  renderLbTable();
}

function lbVal(c, k) {
  const mw = c.min_wage || {};
  return {
    rank: c._rank, name: c.name, harmonised: c.harmonised, national: c.national, gap: c.gap, youth: c.youth,
    lu4: c.lu4, participation: c.participation, pchg: c.participation_change_5y,
    grade: { High: 0, Medium: 1, Low: 2 }[c.grade], changes: c._changes,
    mw_usd: mw.usd, mw_ppp: mw.ppp, mw_avg: mw.pct_of_average,
  }[k];
}

function renderLbTable() {
  const q = document.getElementById("lb-q").value.trim().toLowerCase();
  const reg = document.getElementById("lb-region").value, gr = document.getElementById("lb-grade").value;
  const { k, asc } = lbState.sort;
  const rows = lbState.data.countries.filter((c) => (!q || c.name.toLowerCase().includes(q) || c.iso3.toLowerCase() === q)
    && (!reg || c.region === reg) && (!gr || c.grade === gr))
    .sort((a, b) => {
      const va = lbVal(a, k), vb = lbVal(b, k);
      if (va == null) return 1;
      if (vb == null) return -1;
      const r = typeof va === "string" ? va.localeCompare(vb) : va - vb;
      return asc ? r : -r;
    });
  document.querySelectorAll("#lb-tbl th").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.k === k);
    th.classList.toggle("asc", th.dataset.k === k && asc);
  });
  document.getElementById("lb-count").textContent = `${rows.length} of ${lbState.data.countries.length} countries`;
  document.querySelector("#lb-tbl tbody").innerHTML = rows.map((c) => {
    const mw = c.min_wage;
    return `<tr data-iso="${esc(c.iso3)}">
      <td><span class="flag">${esc(c.flag || "")}</span>${esc(c.name)}</td>
      <td class="num"><strong>${lbPct(c.harmonised)}</strong></td>
      <td class="num">${c.national != null ? `${lbPct(c.national)} <span class="muted">${c.national_year}</span>` : "—"}</td>
      <td class="num ${c.gap != null && Math.abs(c.gap) >= 2 ? "flagcell" : ""}">${c.gap != null ? lbPp(c.gap) : "—"}</td>
      <td class="num">${lbPct(c.youth)}</td>
      <td class="num">${c.lu4 != null ? lbPct(c.lu4) : "—"}</td>
      <td class="num">${lbPct(c.participation)}</td>
      <td class="num ${c.participation_change_5y != null && c.participation_change_5y <= -2 ? "flagcell" : ""}">${lbPp(c.participation_change_5y)}</td>
      <td>${gradeBadge(c.grade)}</td>
      <td class="num">${c._changes || "—"}</td>
      <td class="num">${mw ? lbMoney(mw.usd) : "—"}</td>
      <td class="num">${mw && mw.ppp != null ? lbMoney(mw.ppp) : "—"}</td>
      <td class="num">${mw && mw.pct_of_average != null ? lbPct(mw.pct_of_average, 0) : "—"}</td>
    </tr>`;
  }).join("");
}

// ------------------------------------------------------------------ detail
function selectLabour(iso3, scroll) {
  const c = lbState.data.countries.find((x) => x.iso3 === iso3);
  if (!c) return;
  lbState.sel = iso3;
  if (typeof setTabSub === "function" && !document.getElementById("pane-labour").hidden) setTabSub(iso3);
  const box = document.getElementById("lb-detail");
  box.hidden = false;
  const mw = c.min_wage;
  const recent = c.recent ? `${lbPct(c.recent[1])} <span class="muted">${esc(c.recent[0].replace("-M", "-").replace("-Q", " Q"))}, seasonally adj.</span>` : "—";
  box.innerHTML = `
    <div class="bd-head"><span class="bd-flag">${esc(c.flag || "")}</span>
      <div><h2>${esc(c.name)} ${gradeBadge(c.grade)} <span class="muted small">comparability</span></h2>
      <div class="muted">${c.grade_reasons.length ? esc(c.grade_reasons.join("; ")) + "." : "National survey matches the ILO standard closely; no recent method changes found."}</div></div>
      <button class="close lb-close" onclick="document.getElementById('lb-detail').hidden=true" aria-label="Close">×</button>
    </div>
    <div class="bd-stats">
      <div><span class="l">ILO harmonised (${c.harmonised_year})</span><span class="v">${lbPct(c.harmonised)}</span></div>
      <div><span class="l">National survey (${c.national_year ?? "—"})</span><span class="v">${lbPct(c.national)} ${c.gap != null ? `<span class="muted">${lbPp(c.gap)} vs ILO</span>` : ""}</span></div>
      <div><span class="l">Latest national monthly/quarterly</span><span class="v">${recent}</span></div>
      <div><span class="l">Youth 15–24 (ILO harmonised)</span><span class="v">${lbPct(c.youth)}</span></div>
      <div><span class="l">Broad measure LU4${c.lu4_year ? ` (${c.lu4_year})` : ""}</span><span class="v">${lbPct(c.lu4)}</span></div>
      <div><span class="l">Participation (5-yr change)</span><span class="v">${lbPct(c.participation)} <span class="muted">${lbPp(c.participation_change_5y)}</span></span></div>
    </div>
    ${c.coverage.length ? `<p class="cov">National survey coverage: <strong>${esc(c.coverage.join(", "))}</strong>.</p>` : ""}
    ${c.national_survey ? `<p class="muted small">National source: ${esc(c.national_survey)}.</p>` : ""}
    <div class="bd-grid">
      <div class="card"><h3>Unemployment over time</h3><div class="legend" id="lg-lb"></div><div id="ch-lb" class="chart"></div>
        <p class="caption">Vertical dashed lines mark years with a definition, survey or coverage change, or a break in series. Dashed blue = ILO projection.</p></div>
      <div class="bd-text">
        <div class="card"><h3>Is unemployment hidden?</h3>${c.hidden.length ? c.hidden.map((h) => `<p>${esc(h)}</p>`).join("")
          : `<p class="muted">No strong sign of hidden unemployment in the available data${c.lu4 == null ? " (no broad LU4 measure published)" : ""}.</p>`}</div>
        <div class="card"><h3>Minimum wage</h3>${mw ? `
          <p><strong>${mw.lcu != null ? Math.round(mw.lcu).toLocaleString("en") + " " + esc(mw.currency || "") : "—"}</strong> a month (${mw.year})${mw.type ? ` · ${esc(mw.type.toLowerCase())}` : ""}</p>
          <p>${lbMoney(mw.usd)} at market exchange rates${mw.usd_note ? ` <span class="muted">(${esc(mw.usd_note)})</span>` : ""} ·
            ${mw.ppp != null ? `${lbMoney(mw.ppp)} in purchasing power (PPP, ${mw.ppp_year})` : "PPP not available"}.</p>
          <p>${mw.pct_of_average != null ? `Equal to <strong>${lbPct(mw.pct_of_average, 0)}</strong> of average monthly earnings (${mw.average_year}). ` : ""}
            ${mw.change_5y_pct != null ? `Nominal change over 5 years: <strong>${mw.change_5y_pct > 0 ? "+" : ""}${mw.change_5y_pct}%</strong>${Math.abs(mw.change_5y_pct) > 60 ? " (high inflation erodes much of this)" : ""}.` : ""}</p>`
          : `<p class="muted">No statutory minimum wage in ILO data. Wages may be set by collective agreements instead.</p>`}</div>
      </div>
    </div>
    <div class="card"><h3>Definition &amp; method history</h3>
      ${c.events.length ? c.events.map((e) => `<div class="lb-hist ${e.auto ? "" : "curated"}">
        <span class="lb-ev-y">${e.year ?? "ongoing"}</span>
        <span><strong>${esc(e.title)}</strong> <span class="evtype et-${esc(EV_TYPES[e.type]?.group || "survey")}">${esc(EV_TYPES[e.type]?.label || e.type)}</span>
          ${e.auto ? '<span class="taga">auto</span>' : '<span class="tagc">hand-checked</span>'}<br>
          <span class="muted">${esc(e.detail)}</span>${e.source ? ` <a href="${esc(e.source)}" target="_blank" rel="noopener">source</a>` : ""}</span>
      </div>`).join("") : `<p class="muted">No changes found in ILO metadata or our notes.</p>`}
    </div>`;
  drawLbChart(c);
  if (scroll) box.scrollIntoView({ behavior: "smooth", block: "start" });
}

function drawLbChart(c) {
  const cNat = cssVar("--k-leg"), cHar = cssVar("--k-pres");
  const est = lbState.data.estimate_year;
  const har = c.history.harmonised.filter((p) => p[0] <= est), proj = c.history.harmonised.filter((p) => p[0] >= est);
  const nat = c.history.national;
  legend("lg-lb", [["ILO harmonised (same definition everywhere)", cHar], ["ILO projection", cHar, true], ["National survey", cNat]]);
  const box = document.getElementById("ch-lb");
  const W = 520, H = 240, m = { l: 36, r: 46, t: 10, b: 24 };
  const all = har.concat(proj, nat);
  const x = d3.scaleLinear().domain(d3.extent(all, (p) => p[0])).range([m.l, W - m.r]);
  const y = d3.scaleLinear().domain([0, d3.max(all, (p) => p[1]) * 1.1]).nice(5).range([H - m.b, m.t]);
  const svg = d3.select(box).html("").append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
    .attr("aria-label", `${c.name}: ILO harmonised ${lbPct(c.harmonised)}, national ${lbPct(c.national)}`);
  svg.append("g").attr("class", "grid").selectAll("line").data(y.ticks(5)).join("line")
    .attr("x1", m.l).attr("x2", W - m.r).attr("y1", y).attr("y2", y);
  svg.append("g").attr("class", "yax").selectAll("text").data(y.ticks(5)).join("text")
    .attr("x", m.l - 6).attr("y", (v) => y(v) + 4).attr("text-anchor", "end").text((v) => v + "%");
  svg.append("g").attr("class", "xax").selectAll("text").data(x.ticks(6).filter(Number.isInteger)).join("text")
    .attr("x", x).attr("y", H - 6).attr("text-anchor", "middle").text((v) => v);
  // change markers
  const [x0, x1] = x.domain();
  svg.append("g").selectAll("line").data(c.history.breaks.filter((b) => b >= x0 && b <= x1)).join("line")
    .attr("class", "brk").attr("x1", x).attr("x2", x).attr("y1", m.t).attr("y2", H - m.b)
    .append("title").text((b) => `${b}: definition, survey or coverage change`);
  const ln = d3.line().x((p) => x(p[0])).y((p) => y(p[1]));
  const draw = (pts, color, dashed, dots) => {
    if (!pts.length) return;
    svg.append("path").attr("class", "series").attr("stroke", color).attr("d", ln(pts)).attr("stroke-dasharray", dashed ? "5 4" : null);
    if (dots) svg.append("g").selectAll("circle").data(pts).join("circle").attr("cx", (p) => x(p[0])).attr("cy", (p) => y(p[1]))
      .attr("r", 2.5).attr("fill", color).append("title").text((p) => `${p[0]}: ${lbPct(p[1])}`);
  };
  draw(har, cHar, false, true);
  draw(proj, cHar, true, false);
  draw(nat, cNat, false, true);
  [[har.at(-1), cHar], [nat.at(-1), cNat]].forEach(([p, col]) => {
    if (p) svg.append("text").attr("class", "dlabel").attr("x", x(p[0]) + 6).attr("y", y(p[1]) + 4).attr("fill", col).text(lbPct(p[1]));
  });
}
