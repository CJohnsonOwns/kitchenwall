// Shopping lists: switch between separate lists, add, tick, edit, delete with
// Undo, and create / rename / delete lists. Polls the server every few seconds
// while the page is visible so both phones stay in step.
(function () {
  const root = document.getElementById("list");
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const listId = Number(root.dataset.list);
  const q = (path) => path + (path.includes("?") ? "&" : "?") + "l=" + listId;
  const openList = $("list-open"), gotList = $("list-got"), input = $("list-input");
  const dot = $("sync-dot"), dotText = dot.querySelector("span");
  let version = root.dataset.version, editing = null, pollTimer = null, busy = 0;

  // ---- toast with Undo ----
  const toast = $("toast"), toastText = $("toast-text"), toastUndo = $("toast-undo");
  let toastTimer = null, undoFn = null;
  function showToast(text, undo) {
    toastText.textContent = text;
    undoFn = undo || null;
    toastUndo.hidden = !undo;
    toast.hidden = false;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hideToast, undo ? 8000 : 4000);
  }
  function hideToast() { toast.classList.remove("show"); toast.hidden = true; }
  toastUndo.addEventListener("click", () => { const fn = undoFn; hideToast(); if (fn) fn(); });

  // ---- server ----
  function setSync(ok) {
    dot.classList.toggle("off", !ok);
    dotText.textContent = ok ? "Up to date" : "Can't reach the server, retrying";
  }
  async function call(url, body) {
    busy++;
    try {
      const r = await fetch(url, body === undefined ? {} : {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (r.status === 303 || r.redirected) { location.reload(); return null; } // signed out
      const data = await r.json();
      setSync(true);
      if (data.gone) { location.href = "/list"; return null; } // this list was deleted on the other phone
      if (data.items) render(data);
      if (!data.ok && data.error) showToast(data.error);
      return data;
    } catch (_) {
      setSync(false);
      return null;
    } finally {
      busy--;
    }
  }

  // ---- rendering ----
  const TICK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg>';
  function row(item) {
    const li = document.createElement("li");
    li.className = "big-item list-item" + (item.checked ? " is-checked" : "");
    li.dataset.id = item.id;
    const tick = document.createElement("button");
    tick.type = "button";
    tick.className = "tick" + (item.checked ? " on" : "");
    tick.dataset.act = "toggle";
    tick.setAttribute("aria-label", (item.checked ? "Put back on the list: " : "Got it: ") + item.text);
    tick.innerHTML = TICK;
    const name = document.createElement("button");
    name.type = "button";
    name.className = "name";
    name.dataset.act = "edit";
    name.title = "Edit";
    name.textContent = item.text;
    li.append(tick, name);
    if (!item.checked) {
      const x = document.createElement("button");
      x.type = "button";
      x.className = "ghost icon row-x";
      x.dataset.act = "delete";
      x.setAttribute("aria-label", "Delete " + item.text);
      x.textContent = "×";
      li.append(x);
    } else {
      li.append(document.createElement("span"));
    }
    return li;
  }
  function renderLists(lists) {
    const nav = $("list-switch");
    nav.replaceChildren(...lists.map((l) => {
      const a = document.createElement("a");
      a.href = "/list?l=" + l.id;
      a.dataset.id = l.id;
      if (l.id === listId) a.setAttribute("aria-current", "page");
      const n = document.createElement("span");
      n.className = "ls-name";
      n.textContent = l.name;
      a.append(n);
      if (l.to_get) {
        const b = document.createElement("span");
        b.className = "badge";
        b.textContent = l.to_get;
        a.append(b);
      }
      return a;
    }));
    const me = lists.find((l) => l.id === listId);
    if (me && !renaming) setTitle(me.name);
    $("list-delete").hidden = lists.length < 2;
    // Header badge counts every list.
    const total = lists.reduce((s, l) => s + l.to_get, 0);
    let badge = $("nav-list-badge");
    const tab = document.querySelector('.tabs a[href="/list"]');
    if (!badge && total && tab) {
      badge = document.createElement("span");
      badge.className = "badge";
      badge.id = "nav-list-badge";
      tab.append(badge);
    }
    if (badge) { badge.textContent = total; badge.hidden = total === 0; }
  }
  function setTitle(name) {
    $("list-title").textContent = name;
    document.title = name + " — Kitchenwall";
    input.placeholder = "Add to " + name + "… (Enter)";
    input.setAttribute("aria-label", "Add to " + name);
  }
  function render(state) {
    version = state.version;
    if (state.lists) renderLists(state.lists);
    if (editing) return; // don't yank the field out from under someone typing; next poll catches up
    const open = state.items.filter((i) => !i.checked), got = state.items.filter((i) => i.checked);
    openList.replaceChildren(...open.map(row));
    gotList.replaceChildren(...got.map(row));
    $("list-empty").hidden = open.length > 0;
    $("got-empty").hidden = got.length > 0;
    $("list-clear").hidden = got.length === 0;
    $("list-count").textContent = open.length + " to get";
  }

  // ---- items ----
  $("list-add").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    input.focus();
    const data = await call(q("/list/items"), { text });
    if (!data) input.value = text; // keep what they typed if it didn't save
  });

  function startEdit(li) {
    const name = li.querySelector(".name");
    const field = document.createElement("input");
    field.type = "text";
    field.maxLength = 200;
    field.value = name.textContent;
    field.className = "name-edit";
    field.setAttribute("aria-label", "Edit item");
    name.replaceWith(field);
    editing = li.dataset.id;
    field.focus();
    field.select();
    let done = false;
    const finish = async (save) => {
      if (done) return;
      done = true;
      editing = null;
      const text = field.value.trim();
      if (save && text && text !== name.textContent) {
        await call(q("/list/items/" + li.dataset.id), { text });
      } else {
        field.replaceWith(name);
      }
    };
    field.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); finish(true); }
      if (e.key === "Escape") finish(false);
    });
    field.addEventListener("blur", () => finish(true));
  }

  root.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const li = btn.closest("li");
    const id = li.dataset.id;
    const act = btn.dataset.act;
    if (act === "toggle") {
      const checked = !li.classList.contains("is-checked");
      li.classList.toggle("is-checked", checked);
      btn.classList.toggle("on", checked);
      await call(q("/list/items/" + id), { checked });
    } else if (act === "edit") {
      startEdit(li);
    } else if (act === "delete") {
      const text = li.querySelector(".name").textContent;
      li.remove();
      const data = await call(q("/list/items/" + id + "/delete"), {});
      if (data && data.undo && data.undo.length) showToast("Deleted “" + text + "”", () => call(q("/list/restore"), { ids: data.undo }));
    }
  });

  $("list-clear").addEventListener("click", async () => {
    const data = await call(q("/list/clear"), {});
    if (data && data.undo && data.undo.length) {
      const n = data.undo.length;
      showToast("Cleared " + n + (n === 1 ? " item" : " items"), () => call(q("/list/restore"), { ids: data.undo }));
    }
  });

  // ---- lists: new / rename / delete ----
  const nameForm = $("list-name-form"), nameInput = $("list-name-input"), nameSave = $("list-name-save");
  let renaming = false;
  function openNameForm(mode) {
    renaming = mode === "rename";
    nameForm.hidden = false;
    nameForm.dataset.mode = mode;
    nameSave.textContent = renaming ? "Save" : "Create";
    nameInput.value = renaming ? $("list-title").textContent : "";
    nameInput.placeholder = renaming ? "List name" : "List name, e.g. Costco";
    nameInput.focus();
    nameInput.select();
  }
  function closeNameForm() { nameForm.hidden = true; renaming = false; }
  $("list-new").addEventListener("click", () => openNameForm("new"));
  $("list-rename").addEventListener("click", () => openNameForm("rename"));
  $("list-name-cancel").addEventListener("click", closeNameForm);
  nameInput.addEventListener("keydown", (e) => { if (e.key === "Escape") closeNameForm(); });
  nameForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = nameInput.value.trim();
    if (!name) return nameInput.focus();
    if (nameForm.dataset.mode === "new") {
      const data = await call("/lists", { name });
      if (data && data.ok) location.href = "/list?l=" + data.id;
    } else {
      const data = await call("/lists/" + listId, { name });
      if (data && data.ok) { closeNameForm(); setTitle(name); }
    }
  });
  $("list-delete").addEventListener("click", async () => {
    const name = $("list-title").textContent;
    if (!confirm("Delete the list “" + name + "” and everything on it?")) return;
    const data = await call("/lists/" + listId + "/delete", {});
    if (data && data.ok) location.href = "/list?l=" + data.next;
  });

  // ---- keep in step with the other phone ----
  async function poll() {
    clearTimeout(pollTimer);
    if (!document.hidden && !busy && !editing) {
      try {
        const r = await fetch(q("/list/items?since=" + encodeURIComponent(version || "")));
        if (r.redirected) { location.reload(); return; }
        const data = await r.json();
        setSync(true);
        if (data.gone) { location.href = "/list"; return; }
        if (!data.same) render(data);
      } catch (_) {
        setSync(false);
      }
    }
    pollTimer = setTimeout(poll, 5000);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
  window.addEventListener("online", poll);
  pollTimer = setTimeout(poll, 5000);
})();
