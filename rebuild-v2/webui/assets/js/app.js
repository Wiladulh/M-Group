/* M-Group v2 WebUI bootstrap.
 * This file intentionally contains no legacy API calls. UI is a cleaned visual
 * baseline; connect features only after versioned v2 API contracts are approved.
 */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const status = $("status");
  if (status) status.textContent = "● API v2 belum terhubung";

  const loginForm = $("loginForm");
  if (loginForm) {
    loginForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const error = $("loginError");
      if (error) error.textContent = "Autentikasi belum diaktifkan. WebUI v2 menunggu kontrak API dan layanan backend baru.";
    });
  }

  const logout = $("logoutButton");
  if (logout) logout.addEventListener("click", () => {
    const error = $("loginError");
    if (error) error.textContent = "Sesi backend v2 belum tersedia.";
  });

  document.querySelectorAll(".tab-btn[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.tab;
      document.querySelectorAll(".tab-btn").forEach((item) => item.classList.toggle("active", item === button));
      document.querySelectorAll(".tab-pane").forEach((pane) => pane.classList.toggle("active", pane.id === "tab-" + tab));
      const title = document.querySelector(".top-title");
      if (title) title.textContent = button.textContent.trim();
    });
  });

  document.querySelectorAll("form:not(#loginForm)").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const target = form.parentElement?.querySelector(".result, .hint[role=status], .hint");
      if (target) target.textContent = "Fitur ini belum tersambung ke backend v2. Tidak ada data yang disimpan.";
    });
  });
})();
