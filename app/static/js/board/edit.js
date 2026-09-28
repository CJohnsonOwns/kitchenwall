// Edit a note's text in place (pencil button or double-click).
import { board, freshen } from "./view.js";

function startEdit(note) {
  if (note.querySelector(".sticky-text-edit")) return;
  const textEl = note.querySelector(".sticky-text");
  const original = textEl.textContent;
  const ta = document.createElement("textarea");
  ta.className = "sticky-text-edit";
  ta.value = original;
  ta.maxLength = 500;
  ta.rows = Math.min(8, Math.max(2, original.split("\n").length + 1));
  textEl.replaceWith(ta);
  ta.focus();
  ta.setSelectionRange(ta.value.length, ta.value.length);

  let finished = false;
  const finish = (save) => {
    if (finished) return;
    finished = true;
    const value = ta.value.trim();
    const span = document.createElement("span");
    span.className = "sticky-text";
    span.textContent = save && value ? value : original;
    ta.replaceWith(span);
    if (save && value && value !== original) {
      fetch(`/board/items/${note.dataset.id}/text`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: value }),
      }).catch(() => {});
      freshen(note);
    }
  };
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); finish(true); }
    else if (e.key === "Escape") { e.preventDefault(); finish(false); }
  });
  ta.addEventListener("blur", () => finish(true));
}

export function init() {
  board.querySelectorAll(".sticky-edit").forEach((btn) => {
    btn.addEventListener("click", () => startEdit(btn.closest(".sticky-note")));
  });
  board.addEventListener("dblclick", (e) => {
    const text = e.target.closest(".sticky-text");
    if (text && !board.classList.contains("drawing")) startEdit(text.closest(".sticky-note"));
  });
}
