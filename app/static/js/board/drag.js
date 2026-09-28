// Pointer handling on the board: drag a note, pan the canvas, pinch to zoom
// (one set of handlers for all three), plus ticking a note done.
import { openPhoto } from "./photos.js";
import { applyTransform, board, clamp, freshen, view, zoomAt, ZOOM_MAX, ZOOM_MIN } from "./view.js";

const pointers = new Map();
let pinchStartDist = 0;
let pinchStartZoom = 1;
let dragEl = null;
let photoDown = null;
let dragStartLeft = "";
let dragStartTop = "";
let offsetX = 0;
let offsetY = 0;
let panning = false;
let panStartX = 0;
let panStartY = 0;
let panOriginX = 0;
let panOriginY = 0;

function onPointerDown(e) {
  if (board.classList.contains("drawing")) return;
  const target = e.target;
  if (
    target.closest(".sticky-checkbox") ||
    target.closest(".sticky-tools") ||
    target.closest(".sticky-text-edit") ||
    target.closest(".cat-popover") ||
    target.closest(".board-tools") ||
    target.closest(".board-zoom-controls")
  ) {
    return;
  }
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pointers.size === 2) {
    // second finger: switch from pan/drag to pinch
    const [a, b] = Array.from(pointers.values());
    pinchStartDist = Math.hypot(a.x - b.x, a.y - b.y);
    pinchStartZoom = view.zoom;
    if (dragEl) { dragEl.classList.remove("dragging"); dragEl = null; }
    panning = false;
    board.classList.remove("panning");
    return;
  }
  const note = target.closest(".sticky-note");
  if (note) {
    dragEl = note;
    photoDown = target.closest(".sticky-photo");
    dragStartLeft = note.style.left;
    dragStartTop = note.style.top;
    const rect = note.getBoundingClientRect();
    offsetX = (e.clientX - rect.left) / view.zoom;
    offsetY = (e.clientY - rect.top) / view.zoom;
    note.setPointerCapture(e.pointerId);
    note.classList.add("dragging");
    return;
  }
  panning = true;
  panStartX = e.clientX;
  panStartY = e.clientY;
  panOriginX = view.panX;
  panOriginY = view.panY;
  board.setPointerCapture(e.pointerId);
  board.classList.add("panning");
}

function onPointerMove(e) {
  if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pointers.size === 2 && pinchStartDist > 0) {
    const [a, b] = Array.from(pointers.values());
    const dist = Math.hypot(a.x - b.x, a.y - b.y);
    const rect = board.getBoundingClientRect();
    const cx = (a.x + b.x) / 2 - rect.left;
    const cy = (a.y + b.y) / 2 - rect.top;
    const target = clamp(pinchStartZoom * (dist / pinchStartDist), ZOOM_MIN, ZOOM_MAX);
    zoomAt(cx, cy, target / view.zoom);
    return;
  }
  if (dragEl) {
    const boardRect = board.getBoundingClientRect();
    let x = (e.clientX - boardRect.left - view.panX) / view.zoom - offsetX;
    let y = (e.clientY - boardRect.top - view.panY) / view.zoom - offsetY;
    x = Math.max(0, x);
    y = Math.max(0, y);
    dragEl.style.left = x + "px";
    dragEl.style.top = y + "px";
  } else if (panning) {
    view.panX = panOriginX + (e.clientX - panStartX);
    view.panY = panOriginY + (e.clientY - panStartY);
    applyTransform();
  }
}

function onPointerUp(e) {
  pointers.delete(e.pointerId);
  if (pointers.size < 2) pinchStartDist = 0;
  if (dragEl) {
    dragEl.classList.remove("dragging");
    // Only a real move counts as touching the note — a plain click/tap
    // shouldn't reset how aged it looks.
    if (dragEl.style.left !== dragStartLeft || dragEl.style.top !== dragStartTop) {
      const id = dragEl.dataset.id;
      const x = parseInt(dragEl.style.left, 10) || 0;
      const y = parseInt(dragEl.style.top, 10) || 0;
      fetch(`/board/items/${id}/position`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y }),
      }).catch(() => {});
      freshen(dragEl);
    } else if (photoDown) {
      // A tap on the photo (no drag) opens it full size.
      openPhoto(dragEl);
    }
    dragEl = null;
    photoDown = null;
  }
  if (panning) {
    panning = false;
    board.classList.remove("panning");
  }
}

export function init() {
  board.addEventListener("pointerdown", onPointerDown);
  document.addEventListener("pointermove", onPointerMove);
  document.addEventListener("pointerup", onPointerUp);
  document.addEventListener("pointercancel", onPointerUp);

  board.querySelectorAll(".sticky-checkbox").forEach((cb) => {
    cb.addEventListener("change", () => {
      const note = cb.closest(".sticky-note");
      const id = note.dataset.id;
      fetch(`/board/items/${id}/toggle`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ checked: cb.checked }),
      }).catch(() => {});
      if (cb.checked) {
        // Checked notes move to History — fade it off the board rather than
        // leaving it sitting there crossed out.
        note.classList.add("completing");
        setTimeout(() => note.remove(), 260);
      }
    });
  });
}
