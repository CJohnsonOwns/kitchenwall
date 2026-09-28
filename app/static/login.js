// Login page: picking a name jumps to the password box.
document.querySelectorAll(".login-who input").forEach((r) =>
  r.addEventListener("change", () => document.getElementById("password").focus()));
