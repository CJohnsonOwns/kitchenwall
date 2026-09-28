// Note categories: the Manage dialog, chips on each note, the filter row +
// search (dims notes that don't match), and the per-note popover.
import { board, freshen } from "./view.js";

const catDataEl = document.getElementById("board-categories");
const categories = catDataEl ? JSON.parse(catDataEl.textContent || "[]") : [];  // sorted by name
const catManager = document.getElementById("cat-manager");

function noteCategoryIds(note) {
  return (note.dataset.categories || "").split(",").filter(Boolean);
}

function openCatManager() {
  if (catManager && !catManager.open) catManager.showModal();
}

function renderNoteChips(note) {
  const box = note.querySelector(".sticky-cats");
  if (!box) return;
  const ids = new Set(noteCategoryIds(note));
  box.replaceChildren(
    ...categories
      .filter((c) => ids.has(String(c.id)))
      .map((c) => {
        const chip = document.createElement("span");
        chip.className = "cat-chip";
        chip.style.setProperty("--cat", c.color);
        chip.textContent = c.name;
        return chip;
      })
  );
}

// Filter row + search: dim notes that don't match.
let activeFilter = "";
let query = "";
function applyFilter() {
  board.querySelectorAll(".sticky-note").forEach((note) => {
    const textEl = note.querySelector(".sticky-text, .sticky-text-edit");
    const text = (textEl ? (textEl.value ?? textEl.textContent) : "").toLowerCase();
    const author = (note.querySelector(".sticky-author")?.textContent || "").toLowerCase();
    const miss =
      (activeFilter !== "" && !noteCategoryIds(note).includes(activeFilter)) ||
      (query !== "" && !text.includes(query) && !author.includes(query));
    note.classList.toggle("filtered-out", miss);
  });
}

// Per-note popover: tick categories on/off, saved immediately.
let openPopover = null;

function closeCatPopover() {
  if (!openPopover) return;
  const note = openPopover.closest(".sticky-note");
  note.classList.remove("popover-open");
  note.querySelector(".sticky-tag-btn").setAttribute("aria-expanded", "false");
  openPopover.remove();
  openPopover = null;
}

function saveNoteCategories(note, selected) {
  note.dataset.categories = categories
    .filter((c) => selected.has(String(c.id)))
    .map((c) => c.id)
    .join(",");
  renderNoteChips(note);
  freshen(note);
  applyFilter();
  fetch(`/board/items/${note.dataset.id}/categories`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category_ids: noteCategoryIds(note).map(Number) }),
  }).catch(() => {});
}

function openCatPopover(note, btn) {
  closeCatPopover();
  const pop = document.createElement("div");
  pop.className = "cat-popover";
  pop.setAttribute("role", "group");
  pop.setAttribute("aria-label", "Categories");
  const selected = new Set(noteCategoryIds(note));

  if (!categories.length) {
    const empty = document.createElement("div");
    empty.className = "cat-popover-empty";
    empty.textContent = "No categories yet.";
    pop.appendChild(empty);
  }
  categories.forEach((c) => {
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = selected.has(String(c.id));
    box.addEventListener("change", () => {
      if (box.checked) selected.add(String(c.id));
      else selected.delete(String(c.id));
      saveNoteCategories(note, selected);
    });
    const dot = document.createElement("span");
    dot.className = "cat-dot";
    dot.style.setProperty("--cat", c.color);
    label.append(box, dot, document.createTextNode(c.name));
    pop.appendChild(label);
  });

  const manage = document.createElement("button");
  manage.type = "button";
  manage.className = "cat-popover-manage";
  manage.textContent = categories.length ? "Manage categories…" : "Create a category…";
  manage.addEventListener("click", () => {
    closeCatPopover();
    openCatManager();
  });
  pop.appendChild(manage);

  note.appendChild(pop);
  note.classList.add("popover-open");
  btn.setAttribute("aria-expanded", "true");
  openPopover = pop;
  const firstBox = pop.querySelector("input");
  if (firstBox) firstBox.focus({ preventScroll: true });
}

export function init() {
  const openCatManagerBtn = document.getElementById("open-cat-manager");
  if (openCatManagerBtn) openCatManagerBtn.addEventListener("click", openCatManager);
  if (catManager) {
    // Category forms redirect back to /whiteboard#categories: reopen the dialog.
    if (location.hash === "#categories") openCatManager();
    catManager.addEventListener("close", () => {
      if (location.hash || location.search) history.replaceState(null, "", location.pathname);
    });
  }

  const filterRow = document.getElementById("cat-filter");
  if (filterRow) {
    filterRow.querySelectorAll("button[data-filter]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeFilter = btn.dataset.filter;
        filterRow.querySelectorAll("button[data-filter]").forEach((b) => {
          b.setAttribute("aria-pressed", b === btn ? "true" : "false");
        });
        applyFilter();
      });
    });
  }
  const searchBox = document.getElementById("note-search");
  if (searchBox) {
    searchBox.addEventListener("input", () => {
      query = searchBox.value.trim().toLowerCase();
      applyFilter();
    });
  }

  board.querySelectorAll(".sticky-tag-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const note = btn.closest(".sticky-note");
      if (openPopover && openPopover.parentElement === note) closeCatPopover();
      else openCatPopover(note, btn);
    });
  });
  document.addEventListener("pointerdown", (e) => {
    if (openPopover && !e.target.closest(".cat-popover") && !e.target.closest(".sticky-tag-btn")) {
      closeCatPopover();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && openPopover) {
      const btn = openPopover.closest(".sticky-note").querySelector(".sticky-tag-btn");
      closeCatPopover();
      btn.focus();
    }
  });
}
