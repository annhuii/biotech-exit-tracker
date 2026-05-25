// Shared utilities for the dashboard
const fmtUSD = (n) => {
  if (n == null || n === 0) return "—";
  if (n >= 1) return `$${n.toFixed(1)}B`;
  return `$${(n * 1000).toFixed(0)}M`;
};

const fmtUSDm = (n) => {
  if (n == null || n === 0) return "—";
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}B`;
  return `$${n.toLocaleString()}M`;
};

async function loadJSON(path) {
  // Cache-bust in dev so changes show up immediately. GitHub Pages will serve
  // fresh on each deploy anyway, so this is harmless in production.
  const url = path + (path.includes("?") ? "&" : "?") + "_=" + Date.now();
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return res.json();
}

function setActiveNav() {
  const path = window.location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".topnav nav a").forEach((a) => {
    const href = a.getAttribute("href");
    if (href === path) a.classList.add("active");
  });
}

document.addEventListener("DOMContentLoaded", setActiveNav);

// Generic sortable table
function makeSortable(tableEl, getRowValue) {
  const thead = tableEl.querySelector("thead");
  let currentCol = null;
  let asc = false;
  thead.querySelectorAll("th").forEach((th, idx) => {
    th.addEventListener("click", () => {
      if (currentCol === idx) asc = !asc;
      else { currentCol = idx; asc = false; }
      thead.querySelectorAll("th").forEach((t) => t.classList.remove("sorted", "asc"));
      th.classList.add("sorted");
      if (asc) th.classList.add("asc");
      const tbody = tableEl.querySelector("tbody");
      const rows = Array.from(tbody.querySelectorAll("tr"));
      rows.sort((a, b) => {
        const va = getRowValue(a, idx);
        const vb = getRowValue(b, idx);
        if (typeof va === "number" && typeof vb === "number") {
          return asc ? va - vb : vb - va;
        }
        return asc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
      });
      rows.forEach((r) => tbody.appendChild(r));
    });
  });
}
