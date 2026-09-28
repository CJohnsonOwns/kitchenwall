// Photos on notes. The browser makes the thumbnail (makePhotoThumb in app.js):
// the note shows that, and a tap opens the untouched original in the viewer.
import { board, freshen } from "./view.js";

const makeThumb = (file) => window.makePhotoThumb(file);
const viewer = document.getElementById("photo-viewer");

function toast(msg) {
  // Board has no toast strip of its own; a short-lived notice at the top will do.
  let n = document.getElementById("photo-notice");
  if (!n) {
    n = document.createElement("p");
    n.id = "photo-notice";
    n.className = "notice";
    n.setAttribute("role", "alert");
    document.querySelector(".board-top")?.after(n);
  }
  n.textContent = msg;
  clearTimeout(n._t);
  n._t = setTimeout(() => n.remove(), 6000);
}

async function upload(note, file) {
  const fd = new FormData();
  fd.append("photo", file);
  const thumb = await makeThumb(file);
  if (thumb) fd.append("photo_thumb", new File([thumb], "thumb.jpg", { type: "image/jpeg" }));
  note.classList.add("uploading");
  try {
    const r = await fetch(`/board/items/${note.dataset.id}/photo`, { method: "POST", body: fd });
    const data = await r.json();
    if (!data.ok) return toast(data.error || "The photo didn't save.");
    let img = note.querySelector(".sticky-photo");
    if (!img) {
      img = document.createElement("img");
      img.className = "sticky-photo";
      img.alt = "Photo on this note";
      img.draggable = false;
      img.tabIndex = 0;
      img.setAttribute("role", "button");
      img.title = "View full size";
      note.querySelector(".sticky-head").after(img);
    }
    img.src = data.thumb;
    img.dataset.full = data.full;
    const btn = note.querySelector(".sticky-photo-btn");
    if (btn) { btn.title = "Replace photo"; btn.setAttribute("aria-label", "Replace photo"); }
    freshen(note);
    if (viewer && viewer.open && viewer.dataset.id === note.dataset.id) openPhoto(note);
  } catch (_) {
    toast("Couldn't reach the server, so the photo didn't save.");
  } finally {
    note.classList.remove("uploading");
  }
}

// Full-size viewer.
export function openPhoto(note) {
  const img = note.querySelector(".sticky-photo");
  if (!viewer || !img) return;
  viewer.dataset.id = note.dataset.id;
  document.getElementById("pv-img").src = img.dataset.full;
  document.getElementById("pv-open").href = img.dataset.full;
  document.getElementById("pv-caption").textContent = note.querySelector(".sticky-text")?.textContent || "";
  if (!viewer.open) viewer.showModal();
}

export function init() {
  // Composer: pick a photo before adding the note.
  const composer = document.getElementById("composer");
  const cPhoto = document.getElementById("composer-photo");
  const cThumb = document.getElementById("composer-photo-thumb");
  const cChip = document.getElementById("composer-attached");
  if (composer && cPhoto && cThumb && cChip) {
    const clear = () => {
      cPhoto.value = "";
      cThumb.value = "";
      cChip.hidden = true;
      composer.classList.remove("has-photo");
    };
    document.getElementById("composer-attached-clear").addEventListener("click", clear);
    cPhoto.addEventListener("change", async () => {
      const file = cPhoto.files[0];
      if (!file) return clear();
      const thumb = await makeThumb(file);
      const dt = new DataTransfer();
      if (thumb) dt.items.add(new File([thumb], "thumb.jpg", { type: "image/jpeg" }));
      cThumb.files = dt.files;
      document.getElementById("composer-attached-img").src = URL.createObjectURL(thumb || file);
      document.getElementById("composer-attached-name").textContent = file.name.length > 18 ? file.name.slice(0, 15) + "…" : file.name;
      cChip.hidden = false;
      composer.classList.add("has-photo");
      composer.querySelector('input[name="text"]').focus();
    });
  }

  // Existing notes: camera button in the note's tools, and Replace in the viewer.
  const noteInput = document.getElementById("note-photo-input");
  let photoTarget = null;
  if (noteInput) {
    board.addEventListener("click", (e) => {
      const btn = e.target.closest(".sticky-photo-btn");
      if (!btn) return;
      photoTarget = btn.closest(".sticky-note");
      noteInput.value = "";
      noteInput.click();
    });
    noteInput.addEventListener("change", () => {
      if (photoTarget && noteInput.files[0]) upload(photoTarget, noteInput.files[0]);
    });
  }

  board.addEventListener("keydown", (e) => {
    const img = e.target.closest && e.target.closest(".sticky-photo");
    if (img && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openPhoto(img.closest(".sticky-note")); }
  });
  if (viewer) {
    viewer.addEventListener("click", (e) => { if (e.target === viewer) viewer.close(); }); // backdrop
    const note = () => board.querySelector(`.sticky-note[data-id="${viewer.dataset.id}"]`);
    document.getElementById("pv-replace").addEventListener("change", (e) => {
      const n = note();
      if (n && e.target.files[0]) upload(n, e.target.files[0]);
      e.target.value = "";
    });
    document.getElementById("pv-remove").addEventListener("click", async () => {
      const n = note();
      if (!n) return viewer.close();
      try {
        const r = await fetch(`/board/items/${n.dataset.id}/photo/delete`, { method: "POST" });
        if (!(await r.json()).ok) return toast("That note is gone. Someone may have deleted it.");
        n.querySelector(".sticky-photo")?.remove();
        const btn = n.querySelector(".sticky-photo-btn");
        if (btn) { btn.title = "Add a photo"; btn.setAttribute("aria-label", "Add a photo"); }
        viewer.close();
      } catch (_) {
        toast("Couldn't reach the server, so the photo wasn't removed.");
      }
    });
  }
}
