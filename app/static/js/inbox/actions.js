// Toast with Undo, unread badges, and act(): the one call that changes mail
// (archive, delete, star, read state) through /inbox/action.
import { $, $$ } from "./util.js";

const toast = $("#toast"), toastText = $("#toast-text"), toastUndo = $("#toast-undo");
let toastTimer = null, undoFn = null;

export function showToast(text, undo) {
  if (!toast) return;
  toastText.textContent = text;
  undoFn = undo || null;
  toastUndo.hidden = !undo;
  toast.hidden = false;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, undo ? 8000 : 4000);
}
function hideToast() { if (toast) { toast.classList.remove("show"); toast.hidden = true; } }
if (toastUndo) toastUndo.addEventListener("click", () => { const fn = undoFn; hideToast(); if (fn) fn(); });

export function setUnreadBadges(n) {
  $$('.tabs a[href="/inbox"] .badge, .view-seg a:first-child .badge').forEach((b) => { b.textContent = n; b.hidden = !n; });
}

const PAST = { archive: "Archived", trash: "Deleted", read: "Marked read", unread: "Marked unread", star: "Starred", unstar: "Unstarred", inbox: "Moved to inbox", untrash: "Restored" };

export async function act(action, keys, opts = {}) {
  if (!keys.length) return null;
  let res;
  try {
    res = await fetch("/inbox/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, keys, to_inbox: opts.toInbox }),
    });
  } catch (_) {
    showToast("Couldn't reach the dashboard. Nothing changed.");
    return null;
  }
  const data = await res.json().catch(() => ({ ok: false, errors: ["Something went wrong."] }));
  if (typeof data.unread === "number") setUnreadBadges(data.unread);
  if (!data.ok) {
    showToast((data.errors || ["That didn't work."]).join(" "));
    return null;
  }
  if (!opts.quiet) {
    const n = opts.count || 1;
    const label = PAST[action] + (n > 1 ? ` ${n} conversations` : "");
    showToast(label, data.undo && !opts.noUndo ? () => undo(data.undo) : null);
  }
  return data;
}

async function undo(u) {
  const r = await act(u.action, u.keys, { toInbox: u.to_inbox, quiet: true });
  if (r) { showToast("Undone"); setTimeout(() => location.reload(), 500); }
}
