/**
 * 登录页逻辑：加载验证码、提交登录
 */
(function () {
  const form = document.getElementById("login-form");
  const errorEl = document.getElementById("login-error");
  const captchaImg = document.getElementById("captcha-image");
  const captchaIdInput = document.getElementById("captcha_id");
  const captchaCodeInput = document.getElementById("captcha_code");
  const captchaBox = document.getElementById("captcha-box");
  const loginBtn = document.getElementById("login-btn");

  // 已登录则进入主界面
  if (RAGApp.getToken()) {
    location.replace("/");
    return;
  }

  async function loadCaptcha() {
    errorEl.textContent = "";
    try {
      const res = await RAGApp.apiFetch("/auth/captcha");
      if (res.code !== 200 || !res.data) {
        errorEl.textContent = res.message || "验证码加载失败";
        return;
      }
      captchaIdInput.value = res.data.captcha_id;
      captchaImg.src = res.data.image_base64;
      // 固定验证码时自动填入，避免手机端漏填导致“点登录无反应”
      if (res.data.fixed_code) {
        captchaCodeInput.value = res.data.fixed_code;
      }
    } catch (err) {
      errorEl.textContent = "无法连接服务器，请确认后端已启动";
    }
  }

  captchaBox.addEventListener("click", loadCaptcha);

  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    errorEl.textContent = "";
    loginBtn.disabled = true;
    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;
    const captcha_id = captchaIdInput.value;
    const captcha_code = captchaCodeInput.value.trim();

    if (!captcha_id) {
      errorEl.textContent = "验证码未加载，请点击验证码图片刷新";
      loginBtn.disabled = false;
      await loadCaptcha();
      return;
    }
    if (!captcha_code) {
      errorEl.textContent = "请输入验证码（当前固定为 1234）";
      loginBtn.disabled = false;
      return;
    }

    try {
      const res = await RAGApp.apiFetch("/auth/login", {
        method: "POST",
        json: {
          username: username,
          password: password,
          captcha_id: captcha_id,
          captcha_code: captcha_code,
        },
      });
      if (res.code !== 200 || !res.data || !res.data.access_token) {
        errorEl.textContent = res.message || "登录失败";
        captchaCodeInput.value = "";
        await loadCaptcha();
        return;
      }
      RAGApp.setAuth(res.data.access_token, username);
      location.href = "/";
    } catch (err) {
      errorEl.textContent =
        (err && err.message) || "登录请求失败，请稍后重试";
      await loadCaptcha();
    } finally {
      loginBtn.disabled = false;
    }
  });

  loadCaptcha();
})();
