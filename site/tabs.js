"use strict";
/* Tab bar: Elections / Countries / Trade / Central banks.
   The active tab lives in the URL hash so links work: #trade, #trade/CHN, #trade/USA-CHN, #banks/JP.
   Country detail links (#FRA, upper case) are handled by app.js and keep working on any tab.
   Load order: banks.js, then this file. banks.js has its own 3-tab versions of initTabs/tabHash;
   these later declarations replace them, and activateTab() below keeps banks.js's calls working. */

const TAB_NAMES = ["elections", "countries", "trade", "labour", "food", "banks"];
const tabState = { active: "elections", sub: "" };

const hasBanks = () => typeof bankState !== "undefined";

function tabHash() {
  // The banks view keeps its selected bank in bankState.sel (banks.js).
  if (tabState.active === "banks" && hasBanks()) return "#banks" + (bankState.sel ? "/" + bankState.sel : "");
  return "#" + tabState.active + (tabState.sub ? "/" + tabState.sub : "");
}

// Same signature as banks.js's activateTab, so its calls (e.g. "see this country's central bank") still work.
function activateTab(tab, { push = true } = {}) {
  showTab(tab, tab === "banks" && hasBanks() ? bankState.sel || "" : "");
  if (push && !document.getElementById("detail").open) history.replaceState(null, "", tabHash());
}

// Update the sub-path of the active tab (e.g. the selected country) without adding history entries.
function setTabSub(sub) {
  tabState.sub = sub || "";
  history.replaceState(null, "", tabHash());
}

function showTab(name, sub = "") {
  if (!TAB_NAMES.includes(name)) name = "elections";
  const btn = document.getElementById("tab-" + name);
  if (!btn || btn.hidden) name = "elections";
  tabState.active = name;
  tabState.sub = sub;
  if (hasBanks()) {
    bankState.tab = name;
    if (name === "banks" && sub) bankState.sel = sub;
  }
  for (const t of TAB_NAMES) {
    const b = document.getElementById("tab-" + t);
    const p = document.getElementById("pane-" + t);
    if (!b || !p) continue;
    const on = t === name;
    b.setAttribute("aria-selected", on ? "true" : "false");
    b.tabIndex = on ? 0 : -1;
    p.hidden = !on;
  }
  document.dispatchEvent(new CustomEvent("tabshow", { detail: { name, sub } }));
}

function initTabs() {
  // The Central banks view (banks.js) is optional: hide its tab until that script is present.
  if (typeof initBanks !== "function") {
    const b = document.getElementById("tab-banks");
    if (b) b.hidden = true;
  }
  const buttons = [...document.querySelectorAll('.tabs [role="tab"]')];
  buttons.forEach((b) => {
    b.addEventListener("click", () => { showTab(b.dataset.tab); history.replaceState(null, "", tabHash()); });
    b.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
      const vis = buttons.filter((x) => !x.hidden);
      const i = vis.indexOf(b) + (ev.key === "ArrowRight" ? 1 : -1);
      const next = vis[(i + vis.length) % vis.length];
      next.focus();
      next.click();
    });
  });
  const [name, ...rest] = location.hash.slice(1).split("/");
  if (TAB_NAMES.includes(name)) showTab(name, rest.join("/"));
  else showTab("elections");
}
