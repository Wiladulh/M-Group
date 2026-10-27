/* M-Group v2 API client. All admin calls use the environment-provisioned bearer token. */
(() => {
  "use strict";
  const tokenKey = "mgroup-v2-admin-token";
  const basePath = "/api/v2";
  function getToken() {
    try { return sessionStorage.getItem(tokenKey) || ""; } catch (_) { return ""; }
  }
  function setToken(token) {
    try {
      if (token) sessionStorage.setItem(tokenKey, token);
      else sessionStorage.removeItem(tokenKey);
    } catch (_) {}
  }
  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    const token = options.token || getToken();
    if (token) headers.set("Authorization", "Bearer " + token);
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
      throw error;
    }
    return { response, data };
  }
  async function verifyToken(token) {
    setToken(token);
    try {
      await request("/admin/audit?limit=1");
      return true;
    } catch (error) {
      setToken("");
      throw error;
    }
  }
  window.MGroupApiV2 = Object.freeze({
    basePath,
    request,
    getToken,
    setToken,
    clearToken: () => setToken(""),
    verifyToken
  });
})();
