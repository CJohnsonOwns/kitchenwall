// Reply / Reply all / Forward composer under a conversation, the New-message
// dialog, attachments, and drafts (saved on this device only).
import { showToast } from "./actions.js";
import { attachAutocomplete } from "./autocomplete.js";
import { $, $$, escapeHtml, humanSize, store } from "./util.js";

const MODE_LABEL = { reply: "Replying to", replyall: "Replying to everyone on", forward: "Forwarding" };

export function lastMsg(root) { return $$(".msg", root).pop(); }

export function draftKey(root, msg) { return `draft:${root.dataset.account}:${msg.dataset.uid}`; }

export function readDraft(key) {
  const raw = key && store.get(key);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch (_) { return null; }
}

function originalText(msg, mode) {
  const h = JSON.parse(msg.dataset.headers || "{}");
  const tpl = $(".msg-plain", msg);
  const plain = tpl ? tpl.content.textContent.trim() : "";
  if (mode === "forward") {
    return ["---------- Forwarded message ---------", `From: ${h.from || ""}`, `Date: ${h.date || ""}`, `Subject: ${h.subject || ""}`,
      `To: ${h.to || ""}`].concat(h.cc ? [`Cc: ${h.cc}`] : []).join("\n") + "\n\n" + plain;
  }
  return `On ${h.date || ""}, ${h.from || ""} wrote:\n` + plain.split("\n").map((l) => (l ? "> " + l : ">")).join("\n");
}

export function openComposer(root, msg, mode, opts = {}) {
  const form = $("#thread-composer", root);
  if (!form || !msg) return;
  const all = JSON.parse(msg.dataset.compose || "{}");
  const defaults = all[mode] || {};
  const key = draftKey(root, msg);
  const saved = opts.keepBody ? null : readDraft(key);
  const prevAuto = form._auto || {};
  const el = form.elements;

  if (saved && saved.mode === mode) {
    // Coming back to a draft: restore exactly what was typed.
    el.to_address.value = saved.to || ""; el.cc.value = saved.cc || ""; el.bcc.value = saved.bcc || "";
    el.subject.value = saved.subject || ""; el.body.value = saved.body || "";
    if (saved.account_id) el.account_id.value = saved.account_id;
  } else {
    // Switching Reply / Reply all / Forward: take the new mode's recipients
    // and subject, unless the person already changed that field by hand.
    const keep = (field, def) => {
      const cur = el[field].value;
      return opts.keepBody && cur && cur !== (prevAuto[field] || "") ? cur : (def || "");
    };
    el.to_address.value = keep("to_address", defaults.to);
    el.cc.value = keep("cc", defaults.cc);
    el.subject.value = keep("subject", defaults.subject);
    if (!opts.keepBody) { el.bcc.value = ""; el.body.value = ""; el.account_id.value = form.dataset.defaultAccount; }
  }
  form._auto = { to_address: defaults.to || "", cc: defaults.cc || "", subject: defaults.subject || "" };

  el.mode.value = mode;
  el.ref_uid.value = msg.dataset.uid;
  el.draft_key.value = key;
  form.dataset.draft = key;
  form.dataset.mode = mode;
  $$("[data-switch]", form).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.switch === mode)));
  const h = JSON.parse(msg.dataset.headers || "{}");
  const ctx = $(".composer-context", form);
  const who = h.from ? (h.from.replace(/<.*>/, "").replace(/"/g, "").trim() || h.from.replace(/[<>]/g, "")) : "this message";
  if (ctx) ctx.textContent = `${MODE_LABEL[mode]} ${who}${msg === lastMsg(root) ? "" : " (earlier message)"}`;

  // Original preview + forwardable attachments.
  form.classList.toggle("is-forward", mode === "forward");
  $(".original-text", form).textContent = originalText(msg, mode);
  const fwd = $(".fwd-atts", form), list = $(".fwd-att-list", form);
  const atts = JSON.parse(msg.dataset.forwardable || "[]");
  el.fwd_choice.disabled = mode !== "forward" || !atts.length;
  fwd.hidden = mode !== "forward" || !atts.length;
  list.innerHTML = atts.map((a) => `<label class="check-label att-chip"><input type="checkbox" name="fwd_att" value="${a.index}" checked> ${escapeHtml(a.filename)} <span class="muted">${a.size_h}</span></label>`).join("");
  $$('input[name="fwd_att"]', list).forEach((c) => (c.disabled = mode !== "forward"));

  $(".draft-note", form).hidden = !(saved && saved.mode === mode);
  if (form.previousElementSibling !== msg) msg.after(form);
  if (opts.focus) {
    const target = mode === "forward" && !el.to_address.value ? el.to_address : el.body;
    form.scrollIntoView({ block: "start", behavior: "smooth" });
    setTimeout(() => target.focus({ preventScroll: true }), 250);
  }
}

export function wireComposer(form) {
  if (form._wired) return;
  form._wired = true;
  let t = null;
  const note = $(".draft-note", form);
  const el = form.elements;
  const save = () => {
    const key = form.dataset.draft;
    if (!key) return;
    const d = { mode: el.mode.value, account_id: el.account_id.value, to: el.to_address.value, cc: el.cc.value,
      bcc: el.bcc.value, subject: el.subject.value, body: el.body.value };
    if (d.body.trim() || (key === "draft:new" && (d.to || d.subject))) {
      store.set(key, JSON.stringify(d));
      if (note) note.hidden = false;
    }
  };
  form.addEventListener("input", (e) => { if (e.target.type !== "file") { clearTimeout(t); t = setTimeout(save, 400); } });
  const discard = $("[data-discard]", form);
  if (discard) discard.addEventListener("click", () => {
    store.del(form.dataset.draft);
    el.body.value = ""; el.bcc.value = "";
    clearFiles(form);
    if (note) note.hidden = true;
    const dlg = form.closest("dialog");
    if (dlg) { form.reset(); dlg.close(); return; }
    const root = form.closest("#thread");
    if (root) openComposer(root, lastMsg(root), "reply", { focus: false });
  });
  // Ctrl/Cmd + Enter sends.
  form.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", (e) => {
    if (!el.to_address.value.trim() && !el.cc.value.trim() && !el.bcc.value.trim()) {
      e.preventDefault();
      showToast("Add at least one recipient.");
      el.to_address.focus();
    }
  });
  // Attachments picked from this device.
  const input = $(".file-input", form), listEl = $(".file-list", form), clearBtn = $(".clear-files", form);
  if (input) {
    input.addEventListener("change", () => {
      const files = Array.from(input.files || []);
      const total = files.reduce((n, f) => n + f.size, 0);
      listEl.innerHTML = files.map((f) => `<li>${escapeHtml(f.name)} <span class="muted">${humanSize(f.size)}</span></li>`).join("");
      if (total > 24 * 1024 * 1024) listEl.insertAdjacentHTML("beforeend", '<li class="warn">Over Gmail\'s 25 MB limit. Pick fewer files.</li>');
      clearBtn.hidden = !files.length;
    });
    clearBtn.addEventListener("click", () => clearFiles(form));
  }
  $$("input[data-contacts]", form).forEach(attachAutocomplete);
}

function clearFiles(form) {
  const input = $(".file-input", form);
  if (!input) return;
  input.value = "";
  $(".file-list", form).innerHTML = "";
  $(".clear-files", form).hidden = true;
}

// New-message dialog.
export const composeOpen = $("#compose-open");
const compose = $("#compose");
if (compose && composeOpen) {
  const form = $("form.composer-form", compose);
  wireComposer(form);
  composeOpen.addEventListener("click", () => {
    const saved = readDraft("draft:new");
    if (saved) {
      const el = form.elements;
      el.to_address.value = saved.to || ""; el.cc.value = saved.cc || ""; el.bcc.value = saved.bcc || "";
      el.subject.value = saved.subject || ""; el.body.value = saved.body || "";
      if (saved.account_id) el.account_id.value = saved.account_id;
      $(".draft-note", form).hidden = false;
    }
    compose.showModal();
    form.elements.to_address.focus();
  });
}
