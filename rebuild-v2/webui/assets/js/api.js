/* M-Group v2 API client. Admin access uses an HttpOnly server session cookie. */
(() => {
  "use strict";
  const basePath = "/api/v2";
  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    let body = options.body;
    if (body !== undefined && body !== null && !(body instanceof FormData) && typeof body !== "string") {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(body);
    }
    const response = await fetch(basePath + path, {
      method: options.method || "GET",
      headers,
      body,
      credentials: "same-origin",
      cache: "no-store"
    });
    const contentType = response.headers.get("content-type") || "";
    let data;
    if (contentType.includes("application/json")) data = await response.json();
    else if (options.responseType === "blob") data = await response.blob();
    else data = await response.text();
    if (!response.ok) {
      const detail = data && typeof data === "object" ? (data.detail?.code || data.detail || data.message) : data;
      const error = new Error(String(detail || ("HTTP_" + response.status)));
      error.status = response.status;
      error.data = data;
      if (response.status === 401 && !path.endsWith("/auth/login")) {
        window.dispatchEvent(new Event("mgroup:unauthorized"));
      }
      throw error;
    }
    return { response, data };
  }
  async function login(username, password) {
    return request("/admin/auth/login", { method: "POST", body: { username, password } });
  }
  async function currentSession() {
    return request("/admin/auth/me");
  }
  async function logout() {
    return request("/admin/auth/logout", { method: "POST" });
  }
  window.MGroupApiV2 = Object.freeze({ basePath, request, login, currentSession, logout });
})();
