"use strict";
/* Calendar of the current month + world map of countries voting this month.
   Uses `state`, `esc`, `fmtDate`, `openDetail` from app.js. */

const WORLD_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json";
const level = (imp) => (imp >= 75 ? "hi" : imp >= 45 ? "mid" : "lo");
const LEVEL_LABEL = { hi: "High (75%+)", mid: "Medium (45–74%)", lo: "Low (<45%)" };

function monthEvents() {
  const now = new Date();
  const key = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  // One entry per country per date; keep the most important, remember the rest.
  const groups = new Map();
  for (const c of state.countries) {
    for (const e of c.politics.elections) {
      if (!e.date || !e.date.startsWith(key) || ["cancelled", "annulled"].includes(e.status)) continue;
      const g = `${c.iso3}|${e.date}`;
      const cur = groups.get(g);
      if (!cur) groups.set(g, { ...e, country: c, also: [] });
      else if ((e.importance || 0) > (cur.importance || 0)) groups.set(g, { ...e, country: c, also: [cur.name, ...cur.also] });
      else cur.also.push(e.name);
    }
  }
  const list = [...groups.values()].sort((a, b) => a.date.localeCompare(b.date) || b.importance - a.importance);
  return { key, now, list };
}

function renderMonth() {
  const { key, now, list } = monthEvents();
  const monthName = now.toLocaleString("en", { month: "long", year: "numeric" });
  document.getElementById("cal-title").textContent = `Elections in ${monthName}`;
  renderCalendar(key, now, list);
  renderMonthList(list, monthName);
  renderMap(list);
  document.addEventListener("mouseover", (ev) => {
    const el = ev.target.closest("[data-hl]");
    highlight(el ? el.dataset.hl : null);
  });
}

function chip(e) {
  return `<button class="chip lv-${level(e.importance)}" data-iso="${esc(e.country.iso3)}" data-hl="${esc(e.country.iso3)}"
    title="${esc(e.name)} · importance ${e.importance}%">
    <span class="flag">${esc(e.country.flag || "")}</span><span class="cn">${esc(e.country.name)}</span>
    <span class="pct">${e.importance}%</span></button>`;
}

function renderCalendar(key, now, list) {
  const [y, m] = key.split("-").map(Number);
  const first = new Date(y, m - 1, 1);
  const days = new Date(y, m, 0).getDate();
  const lead = (first.getDay() + 6) % 7; // Monday first
  const byDay = {};
  for (const e of list) if (e.date.length === 10) (byDay[+e.date.slice(8)] ||= []).push(e);

  let html = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => `<div class="dow">${d}</div>`).join("");
  for (let i = 0; i < lead; i++) html += `<div class="day pad"></div>`;
  for (let d = 1; d <= days; d++) {
    const evs = byDay[d] || [];
    const isToday = d === now.getDate();
    const past = d < now.getDate();
    html += `<div class="day${isToday ? " today" : ""}${past ? " past" : ""}${evs.length ? " has" : ""}" role="gridcell"
      aria-label="${d} ${esc(now.toLocaleString("en", { month: "long" }))}: ${evs.length} election(s)">
      <div class="dn">${d}${isToday ? ' <span class="tag">today</span>' : ""}</div>${evs.map(chip).join("")}</div>`;
  }
  document.getElementById("cal").innerHTML = html;

  const unfixed = list.filter((e) => e.date.length < 10);
  document.getElementById("cal-unfixed").innerHTML = unfixed.length
    ? `<div class="unfixed"><span class="muted">Expected this month, exact day not set:</span> ${unfixed.map(chip).join("")}</div>`
    : "";
}

function renderMonthList(list, monthName) {
  document.getElementById("month-count").textContent = `${list.length} election${list.length === 1 ? "" : "s"} in ${monthName}`;
  if (!list.length) {
    document.getElementById("month-list").innerHTML = `<div class="empty">No national elections recorded for ${esc(monthName)}.</div>`;
    return;
  }
  document.getElementById("month-list").innerHTML = list.map((e) => `
    <button class="mrow" data-iso="${esc(e.country.iso3)}" data-hl="${esc(e.country.iso3)}">
      <span class="mdate">${e.date.length === 10 ? fmtDate(e.date) : "Date TBC"}</span>
      <span class="mflag">${esc(e.country.flag || "")}</span>
      <span class="mbody">
        <span class="mtitle">${esc(e.country.name)} <span class="muted">· ${esc(e.kind)}</span>
          <span class="badge ${esc(e.status)}">${esc(e.status)}</span></span>
        <span class="mnote">${esc(e.world_note || "")}</span>
        ${e.also.length ? `<span class="muted">Same day: ${esc(e.also.join(", "))}</span>` : ""}
        ${e.winners && e.winners.length ? `<span class="muted">Winner: ${esc(e.winners.join(", "))}</span>` : ""}
      </span>
      <span class="imp" aria-label="Importance ${e.importance}%">
        <span class="imp-v">${e.importance}%</span>
        <span class="meter"><span class="fill lv-${level(e.importance)}" style="width:${e.importance}%"></span></span>
        <span class="imp-l">importance</span>
      </span>
    </button>`).join("");
}

async function renderMap(list) {
  const box = document.getElementById("map");
  document.getElementById("map-legend").innerHTML = ["hi", "mid", "lo"]
    .map((l) => `<span><span class="sw lv-${l}"></span>${LEVEL_LABEL[l]}</span>`).join("") +
    `<span><span class="sw none"></span>No election</span>`;
  if (!window.d3 || !window.topojson) { box.innerHTML = `<div class="empty">Map library failed to load.</div>`; return; }
  let topo;
  try { topo = await fetch(WORLD_URL).then((r) => r.json()); }
  catch { box.innerHTML = `<div class="empty">Could not load the world map.</div>`; return; }

  // Best event per country this month
  const best = new Map();
  for (const e of list) {
    const cur = best.get(e.country.iso3);
    if (!cur || e.importance > cur.importance) best.set(e.country.iso3, e);
  }
  const byNum = new Map(state.countries.filter((c) => c.iso_num).map((c) => [c.iso_num, c]));

  const W = 960, H = 480;
  const features = topojson.feature(topo, topo.objects.countries).features.filter((f) => f.id !== "010");
  const projection = d3.geoNaturalEarth1().fitExtent([[4, 4], [W - 4, H - 4]], { type: "Sphere" });
  const path = d3.geoPath(projection);

  box.innerHTML = "";
  const svg = d3.select(box).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
    .attr("aria-label", `World map: ${best.size} countries hold national elections this month`);
  svg.append("path").attr("class", "sphere").attr("d", path({ type: "Sphere" }));

  const tip = document.getElementById("tip");
  const showTip = (ev, c, e) => {
    tip.innerHTML = `<strong>${esc(c.flag || "")} ${esc(c.name)}</strong>` + (e
      ? `<div>${esc(e.name)}</div><div class="muted">${e.date.length === 10 ? fmtDate(e.date) : "Date TBC"} · importance ${e.importance}%</div>`
      : `<div class="muted">No national election this month</div>`);
    tip.hidden = false;
    const x = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    tip.style.left = x + "px";
    tip.style.top = ev.clientY + 14 + "px";
  };
  const hideTip = () => { tip.hidden = true; };

  svg.append("g").selectAll("path").data(features).join("path")
    .attr("d", path)
    .attr("class", (f) => {
      const c = byNum.get(f.id), e = c && best.get(c.iso3);
      return "land" + (e ? ` lit lv-${level(e.importance)}` : "") + (c ? "" : " nodata");
    })
    .attr("data-hl", (f) => byNum.get(f.id)?.iso3 || null)
    .on("mousemove", (ev, f) => { const c = byNum.get(f.id); if (c) showTip(ev, c, best.get(c.iso3)); })
    .on("mouseleave", hideTip)
    .on("click", (ev, f) => { const c = byNum.get(f.id); if (c) openDetail(c.iso3); });

  // A dot at the capital for every voting country, so small states stay visible.
  const dots = [...best.values()].filter((e) => e.country.lat != null && e.country.lon != null);
  svg.append("g").selectAll("circle").data(dots).join("circle")
    .attr("class", (e) => `dot-cap lv-${level(e.importance)}`)
    .attr("data-hl", (e) => e.country.iso3)
    .attr("cx", (e) => projection([e.country.lon, e.country.lat])[0])
    .attr("cy", (e) => projection([e.country.lon, e.country.lat])[1])
    .attr("r", 5)
    .on("mousemove", (ev, e) => showTip(ev, e.country, e))
    .on("mouseleave", hideTip)
    .on("click", (ev, e) => openDetail(e.country.iso3));
}

function highlight(iso3) {
  document.querySelectorAll(".hl").forEach((el) => el.classList.remove("hl"));
  if (!iso3) return;
  document.querySelectorAll(`[data-hl="${CSS.escape(iso3)}"]`).forEach((el) => el.classList.add("hl"));
}
