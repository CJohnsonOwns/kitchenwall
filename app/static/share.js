// Sharing tab. The page works without this; it adds a photo preview, an
// upload progress bar (videos can be big), the Link field
// toggle, Enter-to-post on comments, and growing text boxes.
(function () {
  const form = document.getElementById("wall-composer");

  // Text boxes grow with what's typed.
  const grow = (t) => { t.style.height = "auto"; t.style.height = t.scrollHeight + 2 + "px"; };
  document.querySelectorAll(".wall textarea").forEach((t) => t.addEventListener("input", () => grow(t)));

  // Comments: Enter posts, Shift+Enter is a new line.
  document.querySelectorAll(".comment-form textarea").forEach((t) =>
    t.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing && t.value.trim()) {
        e.preventDefault();
        t.form.requestSubmit();
      }
    }));

  // Like / React: swap in the post's new reaction row instead of reloading.
  document.addEventListener("submit", async (e) => {
    const f = e.target.closest && e.target.closest(".rx-form");
    if (!f) return;
    e.preventDefault();
    const box = f.closest(".post-reactions");
    const fd = new FormData(f);
    if (e.submitter && e.submitter.name) fd.set(e.submitter.name, e.submitter.value);
    box.classList.add("busy");
    try {
      const r = await fetch(f.action, { method: "POST", body: fd, headers: { "X-Fetch": "1" } });
      if (!r.ok) throw new Error(await r.text());
      if (r.redirected) { location.href = r.url; return; } // the post was deleted
      box.outerHTML = await r.text();
    } catch (_) {
      box.classList.remove("busy");
      f.submit(); // fall back to a normal page load
    }
  });
  // A tap anywhere else closes an open emoji picker.
  document.addEventListener("click", (e) => {
    document.querySelectorAll(".rx-pick[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  });

  if (!form) return;
  const media = document.getElementById("wall-media");
  const chip = document.getElementById("wall-attached");
  const chipImg = document.getElementById("wall-attached-img");
  const chipName = document.getElementById("wall-attached-name");
  const linkBtn = document.getElementById("wall-link-btn");
  const linkRow = document.getElementById("wall-link-row");
  const link = document.getElementById("wall-link");
  const progress = document.getElementById("wall-progress");
  const shareBtn = form.querySelector(".wall-share-btn");

  const mark = () => form.classList.toggle("has-stuff", !!(media.files.length || link.value));

  linkBtn.setAttribute("aria-expanded", "false");
  linkBtn.addEventListener("click", () => {
    const open = linkRow.hidden;
    linkRow.hidden = !open;
    linkBtn.setAttribute("aria-expanded", String(open));
    if (open) link.focus(); else { link.value = ""; mark(); }
  });
  link.addEventListener("input", mark);

  function clearMedia() {
    media.value = "";
    chip.hidden = true;
    chipImg.removeAttribute("src");
    mark();
  }
  document.getElementById("wall-attached-clear").addEventListener("click", clearMedia);

  media.addEventListener("change", () => {
    const file = media.files[0];
    if (!file) return clearMedia();
    const mb = file.size / 1048576;
    chipName.textContent = `${file.name} · ${mb >= 1 ? mb.toFixed(mb >= 10 ? 0 : 1) + " MB" : Math.ceil(file.size / 1024) + " KB"}`;
    chipImg.removeAttribute("src");
    chip.hidden = false;
    mark();
    if (file.type.startsWith("image/")) chipImg.src = URL.createObjectURL(file);
  });

  // Upload with a progress bar, then go where the server sends us.
  form.addEventListener("submit", (e) => {
    if (!media.files.length) return; // small posts: a normal submit is fine
    e.preventDefault();
    const xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    progress.hidden = false;
    shareBtn.disabled = true;
    const label = progress.querySelector("span");
    xhr.upload.addEventListener("progress", (ev) => {
      if (!ev.lengthComputable) return;
      const pct = Math.round((ev.loaded / ev.total) * 100);
      progress.style.setProperty("--p", pct + "%");
      label.textContent = pct < 100 ? `Uploading… ${pct}%` : "Saving…";
    });
    const fail = (msg) => {
      progress.hidden = true;
      shareBtn.disabled = false;
      label.textContent = "Uploading…";
      alertBox(msg);
    };
    xhr.addEventListener("load", () => {
      if (xhr.status < 400) location.href = xhr.responseURL || "/share";
      else fail(xhr.responseText || "That didn't share. Try again?");
    });
    xhr.addEventListener("error", () => fail("Couldn't reach the server, so nothing was shared."));
    xhr.send(new FormData(form));
  });

  function alertBox(msg) {
    let n = document.getElementById("wall-notice");
    if (!n) {
      n = document.createElement("p");
      n.id = "wall-notice";
      n.className = "notice";
      n.setAttribute("role", "alert");
      form.before(n);
    }
    n.textContent = msg;
  }
})();
