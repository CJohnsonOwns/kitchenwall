// Inbox entry point (inbox.html, email_message.html): tidy the URL, keyboard
// shortcuts, and boot. The pieces live next to this file:
//   util.js · actions.js (toast, act) · list.js (rows, selection, pane)
//   thread.js (a conversation) · composer.js · autocomplete.js
import { composeOpen, openComposer } from "./composer.js";
import { actOnRows, focusLi, keysOf, list, move, openInPane, pane, paneLi, rows, search, selected, setFocus, updateBulk, view, wide } from "./list.js";
import { backUrl, initThread, threadAction, threadRoot } from "./thread.js";
import { $, $$, store } from "./util.js";

// A successful send redirects with ?sent=1&dk=<draft key>: that draft is done.
const params = new URLSearchParams(location.search);
if (params.get("sent") && params.get("dk")) store.del(params.get("dk"));
if (params.has("sent") || params.has("dk") || params.has("notice")) {
  params.delete("sent"); params.delete("dk"); params.delete("notice");
  const qs = params.toString();
  history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
}
window.addEventListener("pageshow", (e) => {
  if (e.persisted) $$("button[data-busy]").forEach((b) => { b.disabled = false; if (b.dataset.label) b.textContent = b.dataset.label; });
});

// ---- Keyboard shortcuts ----
const help = $("#kbd-help");
const helpBtn = $("#kbd-help-open");
if (helpBtn && help) helpBtn.addEventListener("click", () => help.showModal());

document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select" || e.target.isContentEditable) {
    if (e.key === "Escape") e.target.blur();
    return;
  }
  if (document.querySelector("dialog[open]")) return;
  const root = threadRoot(pane || document);
  const inThread = !!threadRoot(document) && !list;
  const k = e.key;

  if (k === "?") { if (help) help.showModal(); e.preventDefault(); return; }
  if (k === "c" && composeOpen) { composeOpen.click(); e.preventDefault(); return; }
  if (k === "/" && search) { search.focus(); search.select(); e.preventDefault(); return; }

  if (list) {
    if (k === "j" || k === "ArrowDown") { move(1); e.preventDefault(); return; }
    if (k === "k" || k === "ArrowUp") { move(-1); e.preventDefault(); return; }
    if ((k === "Enter" || k === "o") && focusLi) {
      if (wide()) openInPane(focusLi); else location.href = $("a.mail-row", focusLi).href;
      e.preventDefault(); return;
    }
    if (k === "x" && focusLi) { const c = $(".row-check", focusLi); c.checked = !c.checked; updateBulk(); e.preventDefault(); return; }
    const targets = selected().length ? selected() : (focusLi ? [focusLi] : []);
    const map = { e: "archive", "#": "trash", s: "toggle-star", I: "read", U: "unread" };
    if (map[k] && targets.length && !(k === "e" && view !== "inbox")) {
      const next = rows()[rows().indexOf(targets[targets.length - 1]) + 1];
      actOnRows(map[k], targets).then(() => { if ((k === "e" || k === "#") && next) setFocus(next); });
      e.preventDefault(); return;
    }
  }

  if (root && (inThread || paneLi)) {
    const last = $$(".msg", root).pop();
    const quick = { r: "reply", a: "replyall", f: "forward" }[k];
    if (quick) { openComposer(root, last, quick, { focus: true }); e.preventDefault(); return; }
    if (inThread) {
      const map = { e: "archive", "#": "trash", I: "read", U: "unread" };
      if (k === "s") { const b = $(".star-toggle", root); if (b) b.click(); e.preventDefault(); return; }
      if (map[k]) { threadAction(map[k], root); e.preventDefault(); return; }
      if (k === "u") { location.href = backUrl(); e.preventDefault(); return; }
    }
  }
});

// ---- Boot ----
initThread(document);
if (list && wide()) {
  const openKey = new URLSearchParams(location.search).get("open");
  const li = openKey && $$(".mail-item").find((x) => keysOf(x).includes(openKey));
  if (li) openInPane(li);
  else if (rows()[0]) setFocus(rows()[0]);
}
updateBulk();
