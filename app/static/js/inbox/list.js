// The conversation list: row actions, selection + bulk bar, local filters,
// the reading pane (wide screens) and keyboard focus. Owns the shared list
// state (pane, paneLi, focusLi) that thread.js and shortcuts.js read.
import { act, setUnreadBadges } from "./actions.js";
import { initThread } from "./thread.js";
import { $, $$ } from "./util.js";

export const list = $("#mail-full");
const layout = $("#inbox-layout");
export const pane = $("#reading-pane");
export const view = (new URLSearchParams(location.search).get("view")) || "inbox";
export const wide = () => window.matchMedia("(min-width: 1100px)").matches && pane;
export const rows = () => (list ? $$(".mail-item", list).filter((li) => !li.hidden) : []);
export const keysOf = (li) => li.dataset.keys.split(",").filter(Boolean);

export function removeRows(items) {
  items.forEach((li) => {
    li.classList.add("leaving");
    setTimeout(() => { li.remove(); updateBulk(); updateEmpty(); }, 220);
  });
}
function updateEmpty() {
  const none = $("#mail-none");
  if (none) none.hidden = rows().length > 0;
}

export function setRead(li, read) {
  li.classList.toggle("is-unread", !read);
  li.dataset.unread = read ? "0" : "1";
  const a = $(".mail-row", li);
  if (a) { a.classList.toggle("unread", !read); a.classList.toggle("read", read); }
}
export function setStar(li, on) {
  li.dataset.starred = on ? "1" : "0";
  const b = $(".star-btn", li);
  if (b) { b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); }
}

// Apply an action to list rows, updating the UI after it succeeds.
export async function actOnRows(action, items) {
  if (!items.length) return;
  if (action === "toggle-read") action = items.every((li) => li.dataset.unread === "1") ? "read" : "unread";
  if (action === "toggle-star") action = items.every((li) => li.dataset.starred === "1") ? "unstar" : "star";
  const keys = items.flatMap(keysOf);
  const data = await act(action, keys, { count: items.length });
  if (!data) return;
  if (action === "archive" || action === "trash" || (action === "unstar" && view === "starred")) {
    if (items.some((li) => li.classList.contains("is-open"))) clearPane();
    removeRows(items);
  } else if (action === "read" || action === "unread") {
    items.forEach((li) => setRead(li, action === "read"));
  } else if (action === "star" || action === "unstar") {
    items.forEach((li) => setStar(li, action === "star"));
  }
  clearSelection();
}

// Selection + bulk bar
const selectAll = $("#select-all");
const bulkActions = $("#bulk-actions");
const bulkCount = $("#bulk-count");
export function selected() { return rows().filter((li) => $(".row-check", li).checked); }
export function updateBulk() {
  const sel = selected();
  $$(".mail-item").forEach((li) => li.classList.toggle("selected", $(".row-check", li).checked));
  if (bulkActions) bulkActions.hidden = sel.length === 0;
  if (bulkCount) bulkCount.textContent = sel.length ? `${sel.length} selected` : "Select";
  if (selectAll) {
    const all = rows();
    selectAll.checked = all.length > 0 && sel.length === all.length;
    selectAll.indeterminate = sel.length > 0 && sel.length < all.length;
  }
  if (layout) layout.classList.toggle("selecting", sel.length > 0);
}
function clearSelection() { $$(".row-check").forEach((c) => (c.checked = false)); updateBulk(); }
if (selectAll) selectAll.addEventListener("change", () => { rows().forEach((li) => ($(".row-check", li).checked = selectAll.checked)); updateBulk(); });
$$("[data-bulk]").forEach((b) => b.addEventListener("click", () => actOnRows(b.dataset.bulk, selected())));

if (list) {
  list.addEventListener("change", (e) => { if (e.target.classList.contains("row-check")) updateBulk(); });
  list.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-row-action]");
    if (btn) {
      e.preventDefault();
      const li = btn.closest(".mail-item");
      const action = btn.dataset.rowAction === "star" ? "toggle-star" : btn.dataset.rowAction;
      actOnRows(action, [li]);
      return;
    }
    const link = e.target.closest("a.mail-row");
    if (link && wide() && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
      e.preventDefault();
      openInPane(link.closest(".mail-item"));
    }
  });
}

// Local filters: unread only + instant text filter (Enter searches all of Gmail).
const unreadBtn = $("#unread-toggle");
export const search = $("#mail-search");
let unreadOnly = false;
function applyFilter() {
  const q = view === "search" ? "" : (search ? search.value.trim().toLowerCase() : "");
  $$(".mail-item").forEach((li) => {
    li.hidden = (unreadOnly && li.dataset.unread !== "1") || (q && !li.dataset.text.includes(q));
  });
  updateEmpty();
  updateBulk();
}
if (unreadBtn) unreadBtn.addEventListener("click", () => { unreadOnly = !unreadOnly; unreadBtn.setAttribute("aria-pressed", String(unreadOnly)); applyFilter(); });
if (search && view !== "search") search.addEventListener("input", applyFilter);

// ---- Reading pane (wide screens) ----
export let paneLi = null;
export function clearPane() {
  if (!pane) return;
  paneLi = null;
  $$(".mail-item.is-open").forEach((x) => x.classList.remove("is-open"));
  pane.innerHTML = '<div class="pane-empty"><p>Pick a conversation to read it here.</p></div>';
  const p = new URLSearchParams(location.search); p.delete("open");
  history.replaceState(null, "", location.pathname + (p.toString() ? "?" + p : ""));
}
export async function openInPane(li) {
  if (!li || !pane) return;
  paneLi = li;
  $$(".mail-item.is-open").forEach((x) => x.classList.remove("is-open"));
  li.classList.add("is-open");
  setFocus(li);
  pane.classList.add("loading");
  pane.innerHTML = '<div class="pane-empty"><p>Loading…</p></div>';
  try {
    const res = await fetch(li.dataset.url + "?pane=1&view=" + encodeURIComponent(view));
    pane.innerHTML = await res.text();
  } catch (_) {
    pane.innerHTML = '<p class="notice">Couldn\'t load that conversation.</p>';
  }
  pane.classList.remove("loading");
  pane.scrollTop = 0;
  setRead(li, true);
  const p = new URLSearchParams(location.search); p.set("open", li.dataset.key);
  history.replaceState(null, "", location.pathname + "?" + p);
  const nextInput = $('#thread-composer input[name="next"]', pane);
  if (nextInput) nextInput.value = location.pathname + "?" + p;
  initThread(pane);
  fetch("/inbox/unread-count").then((r) => r.json()).then((d) => setUnreadBadges(d.unread)).catch(() => {});
}

// ---- Keyboard focus in the list ----
export let focusLi = null;
export function setFocus(li) {
  if (focusLi) focusLi.classList.remove("kb-focus");
  focusLi = li;
  if (li) { li.classList.add("kb-focus"); li.scrollIntoView({ block: "nearest" }); }
}
export function move(delta) {
  const all = rows();
  if (!all.length) return;
  let i = focusLi ? all.indexOf(focusLi) : -1;
  i = Math.max(0, Math.min(all.length - 1, i + delta));
  setFocus(all[i]);
  if (wide() && paneLi) openInPane(all[i]);
}
