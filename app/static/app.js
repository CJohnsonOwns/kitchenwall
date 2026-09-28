// Shared behaviour for every page: header clock, display mode, inbox filters.

// A smaller JPEG copy of a photo, made in the browser (no image library on the
// server). Sized for sharp display on high-density phone screens. Used by
// whiteboard notes and profile pictures; null = server shows the original.
window.makePhotoThumb = async function (file, px = 1280, square = false) {
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    const c = document.createElement("canvas");
    if (square) {
      // Centre crop, for profile pictures.
      const side = Math.min(bmp.width, bmp.height);
      c.width = c.height = Math.min(px, side);
      c.getContext("2d").drawImage(bmp, (bmp.width - side) / 2, (bmp.height - side) / 2, side, side, 0, 0, c.width, c.height);
    } else {
      const scale = Math.min(1, px / Math.max(bmp.width, bmp.height));
      c.width = Math.max(1, Math.round(bmp.width * scale));
      c.height = Math.max(1, Math.round(bmp.height * scale));
      c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    }
    bmp.close && bmp.close();
    return await new Promise((res) => c.toBlob(res, "image/jpeg", 0.9));
  } catch (_) {
    return null;
  }
};

// Settings → profile picture: make a square thumbnail, then upload right away.
document.addEventListener("change", async (e) => {
  const input = e.target;
  if (!input.matches || !input.matches("[data-avatar-input]") || !input.files[0]) return;
  const form = input.form;
  const small = await window.makePhotoThumb(input.files[0], 512, true);
  if (small) {
    const dt = new DataTransfer();
    dt.items.add(new File([small], "thumb.jpg", { type: "image/jpeg" }));
    form.querySelector('[name="avatar_thumb"]').files = dt.files;
  }
  form.submit();
});

// Forms (or their submit button) with data-confirm="Question?" ask first. Runs
// in the capture phase, so a "Cancel" also stops other submit handlers.
// (Replaces inline onsubmit="return confirm(...)": the CSP allows no inline script.)
document.addEventListener("submit", (e) => {
  const q = (e.submitter && e.submitter.dataset.confirm) || e.target.dataset.confirm;
  if (q && !confirm(q)) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);

// <select data-autosubmit> saves as soon as a choice is made.
document.addEventListener("change", (e) => {
  if (e.target.matches && e.target.matches("select[data-autosubmit]")) e.target.form.requestSubmit();
});

(function () {
  // ---- Clock ----
  const clock = document.getElementById("clock");
  if (clock) {
    const tick = () => {
      const d = new Date();
      const h = d.getHours() % 12 || 12;
      clock.textContent = h + ":" + String(d.getMinutes()).padStart(2, "0");
    };
    tick();
    setInterval(tick, 10000);
  }

  // ---- Display mode (wall tablet): hide controls, reload periodically ----
  const body = document.body;
  const displayBtn = document.getElementById("display-btn");
  const banner = document.querySelector(".display-banner");
  const exitBtn = document.getElementById("display-exit");
  const store = {
    get() { try { return localStorage.getItem("display") === "1"; } catch (_) { return false; } },
    set(on) { try { on ? localStorage.setItem("display", "1") : localStorage.removeItem("display"); } catch (_) {} },
  };
  let refreshTimer = null;

  function applyDisplay(on) {
    body.classList.toggle("display", on);
    if (banner) banner.hidden = !on;
    clearTimeout(refreshTimer);
    if (on) {
      const minutes = parseInt(body.dataset.refresh || "0", 10);
      if (minutes > 0) refreshTimer = setTimeout(() => location.reload(), minutes * 60 * 1000);
    }
  }
  if (displayBtn) {
    displayBtn.addEventListener("click", () => {
      store.set(true);
      if (location.pathname !== "/") { location.href = "/"; return; }
      applyDisplay(true);
    });
  }
  if (exitBtn) exitBtn.addEventListener("click", () => { store.set(false); applyDisplay(false); });
  if (store.get() && location.pathname === "/") applyDisplay(true);
  else if (store.get()) store.set(false); // navigated away: leave display mode

  // Sticky toolbars sit just under the header, whose height changes on phones.
  const head = document.querySelector(".head");
  if (head) {
    const setHeadH = () => document.documentElement.style.setProperty("--head-h", head.offsetHeight + "px");
    setHeadH();
    window.addEventListener("resize", setHeadH);
  }

  // Buttons with data-busy show a working label while their form submits.
  document.addEventListener("submit", (e) => {
    const btn = e.submitter && e.submitter.dataset && e.submitter.dataset.busy ? e.submitter : e.target.querySelector("button[data-busy]");
    if (!btn || e.defaultPrevented) return;
    setTimeout(() => { btn.disabled = true; btn.dataset.label = btn.textContent; btn.textContent = btn.dataset.busy; }, 0);
  });

  // Inbox behaviour lives in inbox.js.
})();
