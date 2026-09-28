// Calendar page: tap a day to see and add its items without a page load.
(function () {
  const dataEl = document.getElementById("cal-data");
  const grid = document.getElementById("cal-grid");
  const panel = document.getElementById("day-panel");
  if (!dataEl || !grid || !panel) return;

  const data = JSON.parse(dataEl.textContent || "{}");
  const items = data.items || {};
  const layout = document.getElementById("cal-layout");
  const scrim = document.getElementById("scrim");
  const title = document.getElementById("dp-title");
  const sub = document.getElementById("dp-sub");
  const list = document.getElementById("dp-list");
  const dateInput = document.getElementById("dp-date");
  const nextInput = document.getElementById("dp-next");
  const nameInput = panel.querySelector('input[name="name"]');
  const WD = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const MO = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const isPhone = () => window.matchMedia("(max-width: 999px)").matches;

  const parse = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const dayDiff = (s) => Math.round((parse(s) - parse(data.today)) / 86400000);

  function relative(diff) {
    if (diff === 0) return "Today";
    if (diff === 1) return "Tomorrow";
    if (diff === -1) return "Yesterday";
    return diff < 0 ? Math.abs(diff) + " days ago" : "in " + diff + " days";
  }

  function render(ds) {
    const d = parse(ds), its = items[ds] || [], diff = dayDiff(ds);
    const pageUrl = "/calendar?month=" + data.month + "&day=" + ds;
    title.textContent = WD[d.getDay()] + ", " + MO[d.getMonth()] + " " + d.getDate();
    sub.textContent = relative(diff) + " · " + its.length + (its.length === 1 ? " item" : " items");
    dateInput.value = ds;
    nextInput.value = pageUrl;
    list.innerHTML = its.length
      ? its.map((i) => `
        <li class="big-item ${i.paid ? "done" : i.cls}">
          <form method="post" action="/calendar/${i.id}/toggle-paid" class="tick-form">
            <input type="hidden" name="next" value="${esc(pageUrl)}">
            <button type="submit" class="tick ${i.paid ? "on" : ""}" title="${i.paid ? "Mark not done" : "Mark done"}" aria-label="${i.paid ? "Mark not done" : "Mark done"}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg></button>
          </form>
          <div><div class="name">${esc(i.name)}</div><div class="when">${i.time ? esc(i.time) + " · " : ""}${esc(i.cadence)}${i.paid ? " · done" : ""}</div></div>
          <a class="ghost-link" href="/calendar/${i.id}/edit">Edit</a>
        </li>`).join("")
      : `<li class="empty">Nothing on this day yet.</li>`;
    grid.querySelectorAll(".cal-cell[data-date]").forEach((c) => c.classList.toggle("selected", c.dataset.date === ds));
    history.replaceState(null, "", pageUrl);
  }

  function open() { panel.classList.add("open"); if (scrim) scrim.classList.add("open"); }
  function close() { panel.classList.remove("open"); if (scrim) scrim.classList.remove("open"); }

  grid.addEventListener("click", (e) => {
    const cell = e.target.closest(".cal-cell[data-date]");
    if (!cell) return;
    e.preventDefault();
    render(cell.dataset.date);
    if (isPhone()) { open(); setTimeout(() => nameInput && nameInput.focus({ preventScroll: true }), 300); }
  });
  document.getElementById("dp-close").addEventListener("click", close);
  if (scrim) scrim.addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });

  // Arriving with ?day= on a phone means someone tapped a day elsewhere (e.g. the week strip).
  // Checked before render(), which rewrites the URL to include the day.
  const arrivedWithDay = new URLSearchParams(location.search).has("day");
  render(data.selected);
  if (isPhone() && arrivedWithDay) open();

  // Month / agenda toggle (phones only; desktop shows both).
  const toggle = document.querySelector(".cal-view-toggle");
  if (toggle && layout) {
    let view = "month";
    try { view = localStorage.getItem("cal-view") || "month"; } catch (_) {}
    const setView = (v) => {
      view = v;
      layout.dataset.view = v;
      toggle.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.view === v ? "true" : "false"));
      try { localStorage.setItem("cal-view", v); } catch (_) {}
    };
    setView(view);
    toggle.addEventListener("click", (e) => { const b = e.target.closest("button[data-view]"); if (b) setView(b.dataset.view); });
  }
})();
