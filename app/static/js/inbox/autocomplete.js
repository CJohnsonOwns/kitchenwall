// Address autocomplete on To/Cc/Bcc (people you've exchanged mail with).
import { $$, escapeHtml } from "./util.js";

let contactsPromise = null;
function loadContacts() {
  if (!contactsPromise) contactsPromise = fetch("/inbox/contacts").then((r) => r.json()).then((d) => d.contacts || []).catch(() => []);
  return contactsPromise;
}

export function attachAutocomplete(input) {
  const box = document.createElement("ul");
  box.className = "ac-list";
  box.hidden = true;
  input.parentElement.appendChild(box);
  let items = [], active = -1;
  const token = () => {
    const v = input.value, i = v.lastIndexOf(",");
    return { head: i >= 0 ? v.slice(0, i + 1) + " " : "", tail: v.slice(i + 1).trim() };
  };
  const close = () => { box.hidden = true; active = -1; };
  const choose = (c) => {
    const { head } = token();
    // Names with commas etc. must be quoted or "Doe, Jane <j@x>" splits in two.
    const name = c.name && /[,;:"()<>@\[\]\\]/.test(c.name) ? `"${c.name.replace(/(["\\])/g, "\\$1")}"` : c.name;
    const addr = name ? `${name} <${c.email}>` : c.email;
    input.value = (head + addr + ", ").replace(/^\s+/, "");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    close();
    input.focus();
  };
  const render = async () => {
    const q = token().tail.toLowerCase();
    if (!q) return close();
    const all = await loadContacts();
    const taken = input.value.toLowerCase();
    items = all.filter((c) => (c.email.toLowerCase().includes(q) || (c.name || "").toLowerCase().includes(q)) && !taken.includes(c.email.toLowerCase() + ">") && !taken.includes(c.email.toLowerCase() + ","))
      .slice(0, 6);
    if (!items.length) return close();
    active = 0;
    box.innerHTML = items.map((c, i) => `<li class="${i === 0 ? "active" : ""}" data-i="${i}"><b>${escapeHtml(c.name || c.email)}</b>${c.name ? ` <span class="muted">${escapeHtml(c.email)}</span>` : ""}</li>`).join("");
    box.hidden = false;
  };
  input.addEventListener("focus", loadContacts, { once: true });
  input.addEventListener("input", (e) => { if (e.isTrusted !== false) render(); });
  input.addEventListener("keydown", (e) => {
    if (box.hidden) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      $$("li", box).forEach((li, i) => li.classList.toggle("active", i === active));
    } else if ((e.key === "Enter" || e.key === "Tab") && active >= 0) {
      e.preventDefault();
      choose(items[active]);
    } else if (e.key === "Escape") { e.stopPropagation(); close(); }
  });
  box.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[data-i]");
    if (li) { e.preventDefault(); choose(items[+li.dataset.i]); }
  });
  input.addEventListener("blur", () => setTimeout(close, 150));
}
