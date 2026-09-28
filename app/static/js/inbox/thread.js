// A conversation (full page or inside the reading pane): email frames sized to
// their content, expand/collapse, remote-image opt-in, thread actions, and
// wiring the reply composer.
import { act } from "./actions.js";
import { lastMsg, openComposer, readDraft, draftKey, wireComposer } from "./composer.js";
import { clearPane, pane, paneLi, removeRows, setRead, setStar } from "./list.js";
import { $, $$, store } from "./util.js";

// Grow each email frame to its content so the message scrolls with the page,
// not inside a box. The frame is same-origin (no scripts run inside it), so
// the page can measure it.
function sizeFrame(frame) {
  const fit = () => {
    try {
      const doc = frame.contentDocument;
      if (!doc || !doc.body || doc.URL === "about:blank") return false;
      const h = Math.max(doc.documentElement.scrollHeight, doc.body.scrollHeight);
      if (h > 0) frame.style.height = Math.max(80, h + 2) + "px";
      if (!frame.dataset.watching && window.ResizeObserver) {
        frame.dataset.watching = "1";
        new ResizeObserver(() => fit()).observe(doc.body);
        doc.querySelectorAll("img").forEach((img) => img.addEventListener("load", () => fit()));
      }
      return true;
    } catch (_) { return false; }
  };
  frame.addEventListener("load", fit);
  [0, 60, 250, 800, 2000].forEach((ms) => setTimeout(fit, ms));
}

export function threadRoot(scope) { return $("#thread", scope || document); }

export function initThread(scope) {
  const root = threadRoot(scope);
  if (!root) return;
  $$(".message-body-frame", root).forEach(sizeFrame);

  // Expand / collapse individual messages.
  $$(".msg-head", root).forEach((h) => {
    const toggle = (e) => {
      if (e.target.closest("a, button")) return;
      setExpanded(h.closest(".msg"), !h.closest(".msg").classList.contains("expanded"));
    };
    h.addEventListener("click", toggle);
    h.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(e); } });
  });
  const expandAll = $("[data-expand-all]", root);
  if (expandAll) expandAll.addEventListener("click", () => {
    const msgs = $$(".msg", root);
    const open = !msgs.every((m) => m.classList.contains("expanded"));
    msgs.forEach((m) => setExpanded(m, open));
    $("span", expandAll).textContent = open ? "Collapse all" : "Expand all";
  });

  // Remote images: hidden until asked for (tracking pixels). "Always show"
  // remembers the sender on this device.
  const allowed = new Set(JSON.parse(store.get("img-allow") || "[]"));
  $$(".images-bar", root).forEach((bar) => {
    const show = () => {
      const frame = bar.nextElementSibling;
      if (frame && frame.tagName === "IFRAME") {
        frame.removeAttribute("data-watching");
        frame.setAttribute("srcdoc", (frame.getAttribute("srcdoc") || "").replace(/<meta data-hd-block[^>]*>/, ""));
        sizeFrame(frame);
      }
      bar.remove();
    };
    if (allowed.has(bar.dataset.sender)) return show();
    $("[data-show-images]", bar).addEventListener("click", show);
    const always = $("[data-always-images]", bar);
    if (always) always.addEventListener("click", () => {
      allowed.add(bar.dataset.sender);
      store.set("img-allow", JSON.stringify([...allowed].slice(-500)));
      show();
    });
  });

  // Thread-level actions (toolbar + phone bottom bar).
  $$("[data-thread-action]", root).forEach((b) => b.addEventListener("click", () => threadAction(b.dataset.threadAction, root)));

  // Reply / Reply all / Forward: the toolbar acts on the newest message,
  // the small buttons on each message act on that message.
  $$("[data-quick]", root).forEach((b) => b.addEventListener("click", () => openComposer(root, lastMsg(root), b.dataset.quick, { focus: true })));
  $$("[data-mode]", root).forEach((b) => b.addEventListener("click", () => openComposer(root, b.closest(".msg"), b.dataset.mode, { focus: true })));

  const form = $("#thread-composer", root);
  if (form) {
    wireComposer(form);
    $$("[data-switch]", form).forEach((b) => b.addEventListener("click", () => {
      const msg = $(`.msg[data-uid="${CSS.escape(form.elements.ref_uid.value)}"]`, root) || lastMsg(root);
      openComposer(root, msg, b.dataset.switch, { focus: true, keepBody: true });
    }));
    // The reply box is always there under the conversation, ready to type into.
    const lm = lastMsg(root);
    const saved = lm && readDraft(draftKey(root, lm));
    openComposer(root, lm, (saved && saved.mode) || "reply", { focus: false });
  }
  if (!pane) {
    const focusMsg = $$(".msg.expanded", root).pop();
    if (focusMsg && $$(".msg", root).length > 1) focusMsg.scrollIntoView({ block: "start" });
  }
}

function setExpanded(art, open) {
  art.classList.toggle("expanded", open);
  $(".msg-head", art).setAttribute("aria-expanded", String(open));
  if (open) $$(".message-body-frame", art).forEach(sizeFrame);
}

export async function threadAction(action, root) {
  const keys = root.dataset.keys.split(",").filter(Boolean);
  const data = await act(action, keys);
  if (!data) return;
  const inPane = pane && pane.contains(root);
  if (action === "archive" || action === "trash" || action === "unread") {
    if (inPane) {
      const li = paneLi;
      if (li && action !== "unread") removeRows([li]);
      if (li && action === "unread") setRead(li, false);
      clearPane();
    } else {
      setTimeout(() => { location.href = backUrl(); }, action === "unread" ? 150 : 700);
    }
  } else if (action === "star" || action === "unstar") {
    const b = $(".star-toggle", root);
    const on = action === "star";
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", String(on));
    b.dataset.threadAction = on ? "unstar" : "star";
    $("span", b).textContent = on ? "Starred" : "Star";
    if (paneLi) setStar(paneLi, on);
  } else if (action === "inbox") {
    if (!inPane) setTimeout(() => location.reload(), 400);
  }
}

export function backUrl() {
  const a = $("#back-to-list");
  return a ? a.getAttribute("href") : "/inbox";
}
