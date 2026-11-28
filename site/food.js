"use strict";
/* Food tab: diet, self-sufficiency, surpluses/shortfalls and food suppliers (FAOSTAT).
   Uses esc, state (countries with flags), cssVar, setTabSub. Detail files are loaded on demand. */

const fdState = { data: null, cache: {}, sel: null, sort: { k: "rank", asc: true }, partnerGroup: "All food" };

// Chart categories: 7 palette slots in fixed order + neutral "Other".
const FD_CATS = [
  ["Cereals", ["Cereals"]],
  ["Roots & pulses", ["Roots & tubers", "Pulses"]],
  ["Sugar", ["Sugar & sweeteners"]],
  ["Fruits, veg & nuts", ["Fruits, vegetables & nuts"]],
  ["Oils & oilseeds", ["Oilseeds & oils"]],
  ["Meat & fish", ["Meat", "Fish & seafood"]],
  ["Dairy & eggs", ["Dairy & eggs"]],
  ["Other", ["Coffee, tea, cocoa & spices", "Beverages", "Other"]],
];
const fdColor = (i) => (i < 7 ? `var(--fd${i + 1})` : "var(--fd-other)");
const fdTonnes = (kt) => {
  if (kt == null) return "—";
  const a = Math.abs(kt);
  return a >= 1000 ? `${(a / 1000).toFixed(1)} Mt` : a >= 1 ? `${Math.round(a)} kt` : `${Math.round(a * 1000)} t`;
};
const fdMoney = (kusd) => (kusd == null ? "—" : kusd >= 1e6 ? `$${(kusd / 1e6).toFixed(1)} bn` : `$${Math.round(kusd / 1e3)} m`);
const fdFlag = (iso3) => (iso3 && state.countries.find((c) => c.iso3 === iso3)?.flag) || "";

async function initFood() {
  try {
    fdState.data = await fetch("data/food.json", { cache: "no-cache" }).then((r) => r.json());
  } catch {
    document.getElementById("fd-detail").innerHTML = `<div class="panel empty">Food data not available yet.</div>`;
    return;
  }
  const C = fdState.data.countries;
  C.forEach((c, i) => { c._rank = c.gdp_rank || 900 + i; });
  document.getElementById("fd-asof").textContent =
    `Diet & production ${fdState.data.year} · trade ${fdState.data.trade_year} · source: FAOSTAT`;
  const sel = document.getElementById("fd-country");
  sel.innerHTML = C.slice().sort((a, b) => a.name.localeCompare(b.name))
    .map((c) => `<option value="${esc(c.iso3)}">${esc((c.flag || "") + " " + c.name)}</option>`).join("");
  sel.addEventListener("change", () => selectFood(sel.value, false));

  const regions = [...new Set(C.map((c) => c.region).filter(Boolean))].sort();
  document.getElementById("fd-region").insertAdjacentHTML("beforeend", regions.map((r) => `<option>${esc(r)}</option>`).join(""));
  ["fd-q", "fd-region"].forEach((id) => document.getElementById(id).addEventListener("input", renderFoodTable));
  document.querySelectorAll("#fd-tbl th").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.k;
    fdState.sort = { k, asc: fdState.sort.k === k ? !fdState.sort.asc : ["name", "supplier", "top_shortfall", "top_surplus"].includes(k) };
    renderFoodTable();
  }));
  document.querySelector("#fd-tbl tbody").addEventListener("click", (ev) => {
    const tr = ev.target.closest("tr[data-iso]");
    if (tr) selectFood(tr.dataset.iso, true);
  });
  document.getElementById("pane-food").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-fd-group]");
    if (b) { fdState.partnerGroup = b.dataset.fdGroup; renderPartners(fdState.cache[fdState.sel]); }
    const go = ev.target.closest("[data-fd-go]");
    if (go) selectFood(go.dataset.fdGo, true);
  });
  renderFoodTable();

  const [tab, sub] = location.hash.slice(1).split("/");
  const first = tab === "food" && C.some((c) => c.iso3 === sub) ? sub : C[0].iso3;
  selectFood(first, false);
  document.addEventListener("tabshow", (ev) => {
    if (ev.detail.name === "food" && ev.detail.sub && ev.detail.sub !== fdState.sel && C.some((c) => c.iso3 === ev.detail.sub)) {
      selectFood(ev.detail.sub, false);
    }
  });
}

async function selectFood(iso3, scroll) {
  fdState.sel = iso3;
  document.getElementById("fd-country").value = iso3;
  if (typeof setTabSub === "function" && !document.getElementById("pane-food").hidden) setTabSub(iso3);
  const box = document.getElementById("fd-detail");
  if (!fdState.cache[iso3]) {
    box.innerHTML = `<div class="panel empty">Loading…</div>`;
    try {
      fdState.cache[iso3] = await fetch(`data/food/${iso3}.json`, { cache: "no-cache" }).then((r) => r.json());
    } catch {
      box.innerHTML = `<div class="panel empty">No food data for this country.</div>`;
      return;
    }
  }
  if (fdState.sel !== iso3) return; // user picked another country meanwhile
  renderFoodDetail(fdState.cache[iso3]);
  if (scroll) box.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ------------------------------------------------------------------ detail
function renderFoodDetail(c) {
  const kchg = c.kcal_10y_ago ? c.kcal - c.kcal_10y_ago : null;
  const cats = FD_CATS.map(([label, groups], i) => {
    const k = c.groups.filter((g) => groups.includes(g.group)).reduce((s, g) => s + g.kcal, 0);
    return { label, kcal: k, share: c.kcal ? (100 * k) / c.kcal : 0, color: fdColor(i) };
  });
  const deps = c.groups.filter((g) => g.import_dependency != null);
  const p = c.partners;
  const groupPartners = (groupName) => p?.groups?.[groupName]?.partners || [];

  document.getElementById("fd-detail").innerHTML = `
  <section class="panel">
    <div class="bd-head"><span class="bd-flag">${esc(c.flag || "")}</span>
      <div><h2>${esc(c.name)}</h2><div class="muted">${esc(c.region || "")}</div></div></div>
    <div class="bd-stats">
      <div><span class="l">Calories per person per day</span><span class="v">${c.kcal.toLocaleString("en")}
        ${kchg != null ? `<span class="muted">${kchg >= 0 ? "+" : "−"}${Math.abs(kchg)} vs 10 yrs ago</span>` : ""}</span></div>
      <div><span class="l">Protein / fat per day</span><span class="v">${c.protein != null ? Math.round(c.protein) + " g" : "—"} <span class="muted">/ ${c.fat != null ? Math.round(c.fat) + " g" : "—"}</span></span></div>
      <div><span class="l">Calories from animal foods</span><span class="v">${c.animal_share != null ? c.animal_share.toFixed(0) + "%" : "—"}</span></div>
      <div><span class="l">Food imports${p ? ` (${p.year})` : ""}</span><span class="v">${p ? fdMoney(p.total_kusd) : "—"}</span></div>
    </div>
  </section>

  <section class="panel">
    <div class="panel-head"><h2>What people eat</h2><span class="muted">share of daily calories</span></div>
    <div class="fd-stack" role="img" aria-label="Calories by food group: ${esc(cats.filter((x) => x.share >= 1).map((x) => `${x.label} ${x.share.toFixed(0)}%`).join(", "))}">
      ${cats.filter((x) => x.share > 0.3).map((x) => `<span class="fd-seg" style="flex:${x.share};background:${x.color}" title="${esc(x.label)}: ${x.share.toFixed(1)}% (${Math.round(x.kcal)} kcal)">${x.share >= 7 ? `${x.share.toFixed(0)}%` : ""}</span>`).join("")}
    </div>
    <div class="legend fd-legend">${cats.map((x) => `<span><span class="sw" style="background:${x.color}"></span>${esc(x.label)} <strong>${x.share.toFixed(0)}%</strong></span>`).join("")}</div>
    <div class="table-scroll"><table class="fd-foods">
      <thead><tr><th>Top foods</th><th class="num">kcal / day</th><th class="num">kg / person / year</th><th class="num">Grown at home</th></tr></thead>
      <tbody>${c.top_foods.map((f) => `<tr><td>${esc(f.item)}</td><td class="num">${Math.round(f.kcal)}</td><td class="num">${f.kg ? f.kg.toFixed(1) : "—"}</td>
        <td class="num">${f.self_sufficiency != null ? `${Math.min(f.self_sufficiency, 999).toFixed(0)}%` : "—"}</td></tr>`).join("")}</tbody>
    </table></div>
  </section>

  <section class="panel">
    <div class="panel-head"><h2>Grown at home or imported?</h2><span class="muted">FAO import dependency by food group</span></div>
    <div class="fd-dep">${deps.length ? deps.map((g) => `
      <div class="fd-dep-row">
        <span class="fd-dep-l">${esc(g.group)}</span>
        <span class="fd-dep-bar" role="img" aria-label="${esc(g.group)}: ${g.import_dependency.toFixed(0)}% imported">
          <span class="home" style="width:${Math.max(0, 100 - g.import_dependency)}%"></span><span class="imp" style="width:${Math.min(100, g.import_dependency)}%"></span></span>
        <span class="fd-dep-v"><strong>${g.import_dependency.toFixed(0)}%</strong> imported${g.export_ratio != null && g.export_ratio >= 20 ? ` · exports ${g.export_ratio.toFixed(0)}% of supply` : ""}</span>
      </div>`).join("") : `<p class="muted">No import dependency data.</p>`}
      <div class="legend"><span><span class="sw" style="background:var(--fd1)"></span>Home-grown</span><span><span class="sw" style="background:var(--fd2)"></span>Imported</span></div>
    </div>
  </section>

  <div class="fd-two">
    <section class="panel">
      <div class="panel-head"><h2>Shortfalls: what it must buy</h2><span class="muted">net imports</span></div>
      ${c.shortfalls.length ? `<div class="table-scroll"><table class="fd-foods"><thead><tr><th>Food</th><th class="num">Net imports</th><th class="num">Grown at home</th><th>Main suppliers</th></tr></thead><tbody>
        ${c.shortfalls.map((f) => {
          const sp = f.suppliers;
          const sup = f.group === "Fish & seafood" ? `<span class="muted">not in FAO trade data</span>`
            : sp && sp.partners.length ? sp.partners.map((x) => `${esc(fdFlag(x.iso3))} ${esc(x.name)} ${x.share != null ? x.share.toFixed(0) + "%" : ""}`).join(", ")
              + (sp.basis !== f.group ? "" : ` <span class="muted">(all ${esc(f.group.toLowerCase())})</span>`) : "—";
          return `<tr><td>${esc(f.item)}</td><td class="num">${fdTonnes(-f.net_trade)}</td>
            <td class="num">${f.self_sufficiency != null ? Math.min(f.self_sufficiency, 999).toFixed(0) + "%" : "—"}</td><td class="sup">${sup}</td></tr>`;
        }).join("")}</tbody></table></div>` : `<p class="muted">No net imports.</p>`}
    </section>
    <section class="panel">
      <div class="panel-head"><h2>Surpluses: what it sells abroad</h2><span class="muted">net exports</span></div>
      ${c.surpluses.length ? `<div class="table-scroll"><table class="fd-foods"><thead><tr><th>Food</th><th class="num">Net exports</th><th class="num">Production</th></tr></thead><tbody>
        ${c.surpluses.map((f) => `<tr><td>${esc(f.item)}</td><td class="num">${fdTonnes(f.net_trade)}</td><td class="num">${fdTonnes(f.prod)}</td></tr>`).join("")}
        </tbody></table></div>` : `<p class="muted">No food items with net exports.</p>`}
    </section>
  </div>

  <section class="panel" id="fd-partners"></section>`;
  renderPartners(c);
}

function renderPartners(c) {
  const box = document.getElementById("fd-partners");
  if (!box) return;
  const p = c.partners;
  if (!p) {
    box.innerHTML = `<div class="panel-head"><h2>Where it buys food</h2></div><p class="muted">${esc(c.name)} does not report bilateral food imports to FAO.</p>`;
    return;
  }
  const groups = ["All food", ...Object.keys(p.groups)];
  if (!groups.includes(fdState.partnerGroup)) fdState.partnerGroup = "All food";
  const g = fdState.partnerGroup;
  const list = g === "All food" ? p.top : p.groups[g].partners;
  const total = g === "All food" ? p.total_kusd : p.groups[g].total;
  const max = Math.max(...list.map((x) => x.share || 0), 1);
  box.innerHTML = `
    <div class="panel-head"><h2>Where it buys food</h2><span class="muted">share of food import value, ${p.year}</span></div>
    <div class="seg fd-seg-groups" role="group" aria-label="Food group">${groups.map((x) =>
      `<button data-fd-group="${esc(x)}" class="${x === g ? "on" : ""}">${esc(x)}</button>`).join("")}</div>
    <p class="muted small">${esc(g)}: ${fdMoney(total)} of imports in ${p.year}.</p>
    <div class="fd-bars">${list.map((x) => `
      <div class="fd-bar-row">
        <span class="fd-bar-l">${x.iso3 && fdState.data.countries.some((c2) => c2.iso3 === x.iso3)
          ? `<button class="linkbtn" data-fd-go="${esc(x.iso3)}">${esc(fdFlag(x.iso3))} ${esc(x.name)}</button>` : `${esc(fdFlag(x.iso3))} ${esc(x.name)}`}</span>
        <span class="fd-bar-track"><span class="fd-bar" style="width:${(100 * (x.share || 0)) / max}%"></span></span>
        <span class="fd-bar-v">${x.share != null ? x.share.toFixed(1) + "%" : "—"} <span class="muted">${fdMoney(x.value)}</span></span>
      </div>`).join("")}</div>`;
}

// ------------------------------------------------------------------ table
function fdVal(c, k) {
  return {
    rank: c._rank, name: c.name, kcal: c.kcal, kchg: c.kcal_10y_ago ? c.kcal - c.kcal_10y_ago : null, protein: c.protein,
    animal_share: c.animal_share, cereal_dependency: c.cereal_dependency, food_imports_kusd: c.food_imports_kusd,
    supplier: c.top_supplier?.name, top_shortfall: c.top_shortfall, top_surplus: c.top_surplus,
  }[k];
}

function renderFoodTable() {
  const q = document.getElementById("fd-q").value.trim().toLowerCase();
  const reg = document.getElementById("fd-region").value;
  const { k, asc } = fdState.sort;
  const rows = fdState.data.countries.filter((c) => (!q || c.name.toLowerCase().includes(q)) && (!reg || c.region === reg))
    .sort((a, b) => {
      const va = fdVal(a, k), vb = fdVal(b, k);
      if (va == null) return 1;
      if (vb == null) return -1;
      const r = typeof va === "string" ? va.localeCompare(vb) : va - vb;
      return asc ? r : -r;
    });
  document.querySelectorAll("#fd-tbl th").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.k === k);
    th.classList.toggle("asc", th.dataset.k === k && asc);
  });
  document.getElementById("fd-count").textContent = `${rows.length} of ${fdState.data.countries.length} countries`;
  document.querySelector("#fd-tbl tbody").innerHTML = rows.map((c) => {
    const kchg = fdVal(c, "kchg");
    return `<tr data-iso="${esc(c.iso3)}">
      <td><span class="flag">${esc(c.flag || "")}</span>${esc(c.name)}</td>
      <td class="num">${c.kcal.toLocaleString("en")}</td>
      <td class="num">${kchg != null ? (kchg >= 0 ? "+" : "−") + Math.abs(kchg) : "—"}</td>
      <td class="num">${c.protein != null ? Math.round(c.protein) : "—"}</td>
      <td class="num">${c.animal_share != null ? c.animal_share.toFixed(0) + "%" : "—"}</td>
      <td class="num">${c.cereal_dependency != null ? c.cereal_dependency.toFixed(0) + "%" : "—"}</td>
      <td class="num">${fdMoney(c.food_imports_kusd)}</td>
      <td>${c.top_supplier ? `${esc(fdFlag(c.top_supplier.iso3))} ${esc(c.top_supplier.name)} <span class="muted">${c.top_supplier.share.toFixed(0)}%</span>` : "—"}</td>
      <td>${esc(c.top_shortfall || "—")}</td>
      <td>${esc(c.top_surplus || "—")}</td>
    </tr>`;
  }).join("");
}
