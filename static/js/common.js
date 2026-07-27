/**
 * 前端公共工具：API 封装、Token 存取
 */
(function (global) {
  const API_BASE = "/api/v1";
  const TOKEN_KEY = "rag_access_token";
  const USER_KEY = "rag_username";

  function _storage() {
    try {
      const probe = "__rag_storage_probe__";
      localStorage.setItem(probe, "1");
      localStorage.removeItem(probe);
      return localStorage;
    } catch (_err) {
      try {
        return sessionStorage;
      } catch (_err2) {
        return null;
      }
    }
  }

  const store = _storage();

  function getToken() {
    if (!store) return "";
    return store.getItem(TOKEN_KEY) || "";
  }

  function setAuth(token, username) {
    if (!store) {
      throw new Error("浏览器禁止本地存储，无法保存登录状态");
    }
    store.setItem(TOKEN_KEY, token || "");
    if (username) store.setItem(USER_KEY, username);
  }

  function clearAuth() {
    if (!store) return;
    store.removeItem(TOKEN_KEY);
    store.removeItem(USER_KEY);
  }

  function getUsername() {
    if (!store) return "";
    return store.getItem(USER_KEY) || "";
  }

  async function apiFetch(path, options) {
    const opts = options || {};
    const headers = Object.assign({}, opts.headers || {});
    const token = getToken();
    if (token) {
      headers["Authorization"] = "Bearer " + token;
    }
    if (opts.json !== undefined) {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
      delete opts.json;
    }
    const resp = await fetch(API_BASE + path, Object.assign({}, opts, { headers: headers }));
    const contentType = resp.headers.get("content-type") || "";
    if (contentType.indexOf("application/json") >= 0) {
      const data = await resp.json();
      if (resp.status === 401 || data.code === 401) {
        clearAuth();
        if (!location.pathname.endsWith("/login")) {
          location.href = "/login";
        }
      }
      return data;
    }
    return { code: resp.status, message: await resp.text(), data: null };
  }

  global.RAGApp = {
    API_BASE: API_BASE,
    getToken: getToken,
    setAuth: setAuth,
    clearAuth: clearAuth,
    getUsername: getUsername,
    apiFetch: apiFetch,
  };
})(window);
