// The board's pan/zoom view (shared state for every board module), zoom
// buttons + wheel, fullscreen, and "freshen" (touching a note un-ages it).
export const board = document.getElementById("board");
export const canvas = document.getElementById("board-canvas");

// The floating tool bar sits over the board's top-left corner, where new
// notes land, so the default view starts just below it.
const tools = document.getElementById("board-tools");
const homeY = () => (tools && getComputedStyle(tools).position === "absolute" ? tools.offsetHeight + 20 : 0);

// Mutable view state, read and changed by drag.js and doodle.js too.
export const view = { zoom: 1, panX: 0, panY: 0 };
export const ZOOM_MIN = 0.4;
export const ZOOM_MAX = 2.5;
const zoomResetBtn = document.getElementById("zoom-reset");

export function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

export function applyTransform() {
  canvas.style.transform = "translate(" + view.panX + "px," + view.panY + "px) scale(" + view.zoom + ")";
  if (zoomResetBtn) zoomResetBtn.textContent = Math.round(view.zoom * 100) + "%";
}

export function zoomAt(cx, cy, factor) {
  const prevZoom = view.zoom;
  view.zoom = clamp(view.zoom * factor, ZOOM_MIN, ZOOM_MAX);
  view.panX = cx - (cx - view.panX) * (view.zoom / prevZoom);
  view.panY = cy - (cy - view.panY) * (view.zoom / prevZoom);
  applyTransform();
}

// Paper aging: touching a note smooths it out again.
export function freshen(note) {
  note.classList.remove("age-1", "age-2", "age-3");
  note.classList.add("age-0");
}

export function init() {
  view.panY = homeY();
  board.addEventListener(
    "wheel",
    (e) => {
      if (e.target.closest(".cat-popover, .board-tools, .board-zoom-controls, .sticky-text-edit")) return;
      e.preventDefault();
      const rect = board.getBoundingClientRect();
      zoomAt(e.clientX - rect.left, e.clientY - rect.top, e.deltaY < 0 ? 1.1 : 0.9);
    },
    { passive: false }
  );

  const zoomInBtn = document.getElementById("zoom-in");
  const zoomOutBtn = document.getElementById("zoom-out");
  if (zoomInBtn) zoomInBtn.addEventListener("click", () => {
    const rect = board.getBoundingClientRect();
    zoomAt(rect.width / 2, rect.height / 2, 1.2);
  });
  if (zoomOutBtn) zoomOutBtn.addEventListener("click", () => {
    const rect = board.getBoundingClientRect();
    zoomAt(rect.width / 2, rect.height / 2, 1 / 1.2);
  });
  if (zoomResetBtn) zoomResetBtn.addEventListener("click", () => {
    view.zoom = 1;
    view.panX = 0;
    view.panY = homeY();
    applyTransform();
  });
  applyTransform();

  // ---- Fullscreen ----
  const expandBtn = document.getElementById("board-expand");
  const boardFrame = document.getElementById("board-frame");
  if (expandBtn && boardFrame) {
    expandBtn.addEventListener("click", () => {
      if (document.fullscreenElement) {
        document.exitFullscreen();
      } else if (boardFrame.requestFullscreen) {
        boardFrame.requestFullscreen().catch(() => {});
      }
    });
    document.addEventListener("fullscreenchange", () => {
      const active = document.fullscreenElement === boardFrame;
      expandBtn.textContent = active ? "Exit" : "Expand";
      expandBtn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }
}
