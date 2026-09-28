// Whiteboard entry point (_board_widget.html, on /whiteboard and Home).
// The pieces live next to this file, each with an init():
//   view.js (pan/zoom state, fullscreen) · drag.js (drag, pan, pinch, tick done)
//   edit.js · categories.js · doodle.js · photos.js
import * as categories from "./categories.js";
import * as doodle from "./doodle.js";
import * as drag from "./drag.js";
import * as edit from "./edit.js";
import * as photos from "./photos.js";
import * as boardView from "./view.js";

// ---- Board / History sub-tabs (independent of the board/canvas below) ----
const subTabBoard = document.getElementById("sub-tab-board");
const subTabHistory = document.getElementById("sub-tab-history");
const boardViewEl = document.getElementById("board-view");
const historyView = document.getElementById("history-view");
if (subTabBoard && subTabHistory && boardViewEl && historyView) {
  const showHistory = (on) => {
    boardViewEl.hidden = on;
    historyView.hidden = !on;
    subTabBoard.setAttribute("aria-pressed", on ? "false" : "true");
    subTabHistory.setAttribute("aria-pressed", on ? "true" : "false");
  };
  subTabBoard.addEventListener("click", () => showHistory(false));
  subTabHistory.addEventListener("click", () => showHistory(true));
}

if (boardView.board && boardView.canvas) {
  // Same order as the listeners were added in the old single file.
  for (const m of [boardView, drag, edit, categories, doodle, photos]) m.init();
}
