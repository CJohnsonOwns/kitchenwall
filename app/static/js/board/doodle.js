// Arrange / Draw mode, pen colour + width, and freehand doodles (saved as SVG paths).
import { board, view } from "./view.js";

const modeArrangeBtn = document.getElementById("mode-arrange");
const modeDrawBtn = document.getElementById("mode-draw");

function setMode(drawing) {
  board.classList.toggle("drawing", drawing);
  if (modeArrangeBtn) modeArrangeBtn.setAttribute("aria-pressed", drawing ? "false" : "true");
  if (modeDrawBtn) modeDrawBtn.setAttribute("aria-pressed", drawing ? "true" : "false");
}

let currentColor = "#d9a441";
let currentWidth = 4;
const SVG_NS = "http://www.w3.org/2000/svg";

function pathFromPoints(pts) {
  if (!pts.length) return "";
  return "M " + pts.map((p) => `${p[0]} ${p[1]}`).join(" L ");
}

function toCanvasPoint(e) {
  const rect = board.getBoundingClientRect();
  return [
    Math.round((e.clientX - rect.left - view.panX) / view.zoom),
    Math.round((e.clientY - rect.top - view.panY) / view.zoom),
  ];
}

export function init() {
  if (modeArrangeBtn) modeArrangeBtn.addEventListener("click", () => setMode(false));
  if (modeDrawBtn) modeDrawBtn.addEventListener("click", () => setMode(true));

  const swatchesEl = document.getElementById("doodle-swatches");
  if (swatchesEl) {
    swatchesEl.querySelectorAll(".pen").forEach((sw) => {
      sw.addEventListener("click", () => {
        currentColor = sw.dataset.color;
        swatchesEl.querySelectorAll(".pen").forEach((s) => {
          s.setAttribute("aria-pressed", s === sw ? "true" : "false");
        });
        setMode(true);
      });
    });
  }
  const widthsEl = document.getElementById("doodle-widths");
  if (widthsEl) {
    widthsEl.querySelectorAll("button[data-width]").forEach((b) => {
      b.addEventListener("click", () => {
        currentWidth = parseInt(b.dataset.width, 10) || 4;
        widthsEl.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
        setMode(true);
      });
    });
  }

  const svg = document.getElementById("doodle-layer");
  if (!svg) return;
  let drawingStroke = false;
  let points = [];
  let livePath = null;

  svg.addEventListener("pointerdown", (e) => {
    if (!board.classList.contains("drawing")) return;
    drawingStroke = true;
    points = [toCanvasPoint(e)];
    livePath = document.createElementNS(SVG_NS, "path");
    livePath.setAttribute("stroke", currentColor);
    livePath.setAttribute("stroke-width", String(currentWidth));
    livePath.setAttribute("fill", "none");
    livePath.setAttribute("stroke-linecap", "round");
    livePath.setAttribute("stroke-linejoin", "round");
    svg.appendChild(livePath);
    svg.setPointerCapture(e.pointerId);
  });

  svg.addEventListener("pointermove", (e) => {
    if (!drawingStroke) return;
    points.push(toCanvasPoint(e));
    livePath.setAttribute("d", pathFromPoints(points));
  });

  svg.addEventListener("pointerup", () => {
    if (!drawingStroke) return;
    drawingStroke = false;
    if (points.length > 1) {
      const d = pathFromPoints(points);
      fetch("/board/strokes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: d, color: currentColor, width: currentWidth }),
      }).catch(() => {});
    } else if (livePath) {
      livePath.remove();
    }
    livePath = null;
    points = [];
  });
}
