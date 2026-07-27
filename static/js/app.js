/**
 * 主工作区：文档上传列表 + SSE 流式多轮对话 + Markdown 渲染
 */
(function () {
  if (!RAGApp.getToken()) {
    location.replace("/login");
    return;
  }

  const userChip = document.getElementById("user-chip");
  const fileInput = document.getElementById("file-input");
  const btnUpload = document.getElementById("btn-upload");
  const fileListEl = document.getElementById("file-list");
  const chatMessages = document.getElementById("chat-messages");
  const chatInput = document.getElementById("chat-input");
  const btnSend = document.getElementById("btn-send");
  const btnLogout = document.getElementById("btn-logout");
  const btnNewSession = document.getElementById("btn-new-session");
  const appMain = document.getElementById("app-main");
  const mobileTabs = document.getElementById("mobile-tabs");

  let sessionId = localStorage.getItem("rag_session_id") || "";
  let streaming = false;
  let docsPollTimer = null;

  userChip.textContent = RAGApp.getUsername() || "已登录用户";

  if (window.marked) {
    marked.setOptions({ breaks: true, gfm: true });
  }

  function syncDocsPolling(docs) {
    const hasIndexing = (docs || []).some(function (d) {
      return d.status === "indexing";
    });
    if (hasIndexing && !docsPollTimer) {
      docsPollTimer = setInterval(function () {
        refreshDocuments();
      }, 3000);
    } else if (!hasIndexing && docsPollTimer) {
      clearInterval(docsPollTimer);
      docsPollTimer = null;
    }
  }

  function renderMarkdown(text) {
    const raw = text || "";
    if (window.marked && window.DOMPurify) {
      return DOMPurify.sanitize(marked.parse(raw));
    }
    return raw
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\n/g, "<br/>");
  }

  function hideEmpty() {
    const emptyState = document.getElementById("empty-state");
    if (emptyState) emptyState.style.display = "none";
  }

  function showToast(text) {
    const old = document.querySelector(".toast-tip");
    if (old) old.remove();
    const tip = document.createElement("div");
    tip.className = "toast-tip";
    tip.textContent = text;
    document.body.appendChild(tip);
    setTimeout(function () {
      tip.remove();
    }, 1800);
  }

  function setMobilePanel(panel) {
    if (!appMain) return;
    const next = panel === "docs" ? "docs" : "chat";
    appMain.setAttribute("data-mobile-panel", next);
    if (mobileTabs) {
      mobileTabs.querySelectorAll(".mobile-tab").forEach(function (btn) {
        btn.classList.toggle("is-active", btn.getAttribute("data-panel") === next);
      });
    }
    if (next === "chat" && chatInput) {
      try {
        chatInput.focus({ preventScroll: true });
      } catch (_err) {
        /* ignore */
      }
    }
  }

  function appendMessage(role, contentHtml, plainText) {
    hideEmpty();
    const wrap = document.createElement("div");
    wrap.className = "msg " + (role === "user" ? "msg-user" : "msg-assistant");
    const roleLabel = role === "user" ? "我" : "OA智能聊天小助手";
    wrap.innerHTML =
      '<div class="msg-role">' +
      roleLabel +
      '</div><div class="msg-content"></div>';
    const contentEl = wrap.querySelector(".msg-content");
    if (role === "assistant") {
      contentEl.innerHTML = contentHtml || renderMarkdown(plainText || "");
    } else {
      contentEl.textContent = plainText || "";
    }
    chatMessages.appendChild(wrap);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return contentEl;
  }

  function appendToolTip(text) {
    hideEmpty();
    const tip = document.createElement("div");
    tip.className = "tool-tip";
    tip.textContent = text;
    chatMessages.appendChild(tip);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return tip;
  }

  async function ensureSession() {
    if (sessionId) return sessionId;
    const res = await RAGApp.apiFetch("/chat/session/new", { method: "POST" });
    if (res.code !== 200 || !res.data) {
      throw new Error(res.message || "创建会话失败");
    }
    sessionId = res.data.session_id;
    localStorage.setItem("rag_session_id", sessionId);
    return sessionId;
  }

  async function refreshDocuments() {
    try {
      const res = await RAGApp.apiFetch("/documents/list");
      if (res.code !== 200 || !res.data || !Array.isArray(res.data.documents)) {
        syncDocsPolling([]);
        return;
      }
      const docs = res.data.documents;
      renderDocumentList(docs);
      syncDocsPolling(docs);
    } catch (err) {
      console.warn("刷新文档列表失败", err);
    }
  }

  function renderDocumentList(docs) {
    fileListEl.innerHTML = "";
    if (!docs || !docs.length) {
      return;
    }
    docs.forEach(function (doc) {
      const item = document.createElement("div");
      item.className = "file-item";
      item.dataset.documentId = doc.document_id || "";

      const header = document.createElement("div");
      header.className = "file-item-header";

      const nameEl = document.createElement("p");
      nameEl.className = "file-item-name";
      nameEl.textContent = doc.file_name || doc.document_id || "";

      const btnDelete = document.createElement("button");
      btnDelete.className = "btn-file-delete";
      btnDelete.type = "button";
      btnDelete.title = "删除记录";
      btnDelete.textContent = "删除";
      btnDelete.addEventListener("click", function () {
        deleteDocument(doc);
      });

      header.appendChild(nameEl);
      header.appendChild(btnDelete);

      const meta = document.createElement("div");
      meta.className = "file-item-meta";

      const timeEl = document.createElement("span");
      timeEl.className = "file-item-time";
      timeEl.textContent = (doc.upload_time || new Date().toISOString())
        .replace("T", " ")
        .slice(0, 19);

      const statusEl = document.createElement("span");
      const status = doc.status || "indexing";
      statusEl.className = "status-" + status;
      statusEl.textContent = status;

      meta.appendChild(timeEl);
      meta.appendChild(statusEl);

      item.appendChild(header);
      item.appendChild(meta);
      fileListEl.appendChild(item);
    });
  }

  async function deleteDocument(doc) {
    const name = doc.file_name || doc.document_id;
    if (!confirm('确认删除文档 "' + name + '"？\n将同时移除列表记录与知识库索引。')) {
      return;
    }
    try {
      const res = await RAGApp.apiFetch(
        "/documents/" + encodeURIComponent(doc.document_id),
        { method: "DELETE" }
      );
      if (res.code !== 200) {
        alert(res.message || "删除失败");
        return;
      }
      await refreshDocuments();
    } catch (err) {
      alert("删除异常: " + (err.message || err));
    }
  }

  async function uploadFile(file) {
    const form = new FormData();
    form.append("file", file);
    const token = RAGApp.getToken();
    const resp = await fetch(RAGApp.API_BASE + "/documents/upload", {
      method: "POST",
      headers: { Authorization: "Bearer " + token },
      body: form,
    });
    const data = await resp.json();
    if (data.code !== 200) {
      alert(data.message || "上传失败");
      return;
    }

    // 先用上传接口返回值立刻显示记录，再拉列表校准
    const uploaded = (data && data.data) || {};
    const optimistic = {
      document_id: uploaded.document_id,
      file_name: uploaded.file_name || file.name,
      upload_time: new Date().toISOString(),
      status: uploaded.status || "indexing",
    };
    if (optimistic.document_id) {
      const current = [];
      fileListEl.querySelectorAll(".file-item").forEach(function (el) {
        current.push({
          document_id: el.dataset.documentId,
          file_name: (el.querySelector(".file-item-name") || {}).textContent || "",
          upload_time: (el.querySelector(".file-item-time") || {}).textContent || "",
          status: (el.querySelector("[class^='status-']") || {}).textContent || "",
        });
      });
      const exists = current.some(function (d) {
        return d.document_id === optimistic.document_id;
      });
      if (!exists) {
        renderDocumentList([optimistic].concat(current));
      }
      syncDocsPolling([optimistic].concat(current));
    }

    await refreshDocuments();
    // 再补一次，避免偶发读到提交前快照
    setTimeout(function () {
      refreshDocuments();
    }, 500);
  }

  /**
   * 解析 SSE 文本缓冲，按 event/data 拆帧
   */
  function parseSseChunk(buffer, onEvent) {
    const parts = buffer.split("\n\n");
    const rest = parts.pop() || "";
    parts.forEach(function (block) {
      if (!block.trim()) return;
      let eventName = "message";
      let dataLine = "";
      block.split("\n").forEach(function (line) {
        if (line.indexOf("event:") === 0) {
          eventName = line.slice(6).trim();
        } else if (line.indexOf("data:") === 0) {
          dataLine += line.slice(5).trim();
        }
      });
      if (!dataLine) return;
      try {
        onEvent(eventName, JSON.parse(dataLine));
      } catch (err) {
        console.warn("SSE JSON 解析失败", dataLine, err);
      }
    });
    return rest;
  }

  /**
   * 消费 SSE 响应。
   * 部分手机浏览器 / AutoDL 反代下 resp.body 为空，需回退到整包 text 解析。
   */
  async function consumeSse(resp, onEvent) {
    if (resp.body && typeof resp.body.getReader === "function") {
      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      while (true) {
        const result = await reader.read();
        if (result.done) break;
        buffer += decoder.decode(result.value, { stream: true });
        buffer = parseSseChunk(buffer, onEvent);
      }
      if (buffer.trim()) {
        parseSseChunk(buffer + "\n\n", onEvent);
      }
      return;
    }

    const text = await resp.text();
    if (!text || !String(text).trim()) {
      throw new Error("流式接口返回空内容（可能被代理缓冲或浏览器不支持流式读取）");
    }
    parseSseChunk(String(text).endsWith("\n\n") ? text : text + "\n\n", onEvent);
  }

  async function sendMessage() {
    if (streaming) return;
    const text = (chatInput.value || "").trim();
    if (!text) return;

    setMobilePanel("chat");
    streaming = true;
    btnSend.disabled = true;
    chatInput.value = "";
    appendMessage("user", "", text);

    const assistantContentEl = appendMessage("assistant", '<span class="typing-dots"><span></span><span></span><span></span></span>', "");
    let answer = "";
    let toolTipEl = null;

    try {
      await ensureSession();
      const resp = await fetch(RAGApp.API_BASE + "/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          Authorization: "Bearer " + RAGApp.getToken(),
        },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });

      if (!resp.ok) {
        let detail = "";
        try {
          detail = await resp.text();
        } catch (_err) {
          /* ignore */
        }
        throw new Error(
          "流式接口请求失败: HTTP " +
            resp.status +
            (detail ? " " + detail.slice(0, 120) : "")
        );
      }

      await consumeSse(resp, function (eventName, data) {
        if (eventName === "tool_start") {
          const q = (data && data.query) || "";
          toolTipEl = appendToolTip("正在检索知识库: " + q);
        } else if (eventName === "tool_end") {
          if (toolTipEl) toolTipEl.textContent = "知识库检索完成";
        } else if (eventName === "token") {
          answer += (data && data.content) || "";
          assistantContentEl.innerHTML = renderMarkdown(answer);
          chatMessages.scrollTop = chatMessages.scrollHeight;
        } else if (eventName === "error") {
          const msg = (data && data.message) || "对话出错";
          answer += (answer ? "\n\n" : "") + "**错误**: " + msg;
          assistantContentEl.innerHTML = renderMarkdown(answer);
        } else if (eventName === "done") {
          if (!answer && data && data.answer) {
            answer = data.answer;
            assistantContentEl.innerHTML = renderMarkdown(answer);
          }
          if (!answer) {
            assistantContentEl.innerHTML = renderMarkdown("（未生成有效回复）");
          }
        }
      });

      if (!answer) {
        assistantContentEl.innerHTML = renderMarkdown("（未生成有效回复）");
      }
    } catch (err) {
      assistantContentEl.innerHTML = renderMarkdown("请求失败：" + (err.message || err));
    } finally {
      streaming = false;
      btnSend.disabled = false;
      chatInput.focus();
    }
  }

  btnUpload.addEventListener("click", function () {
    fileInput.click();
  });

  fileInput.addEventListener("change", async function () {
    const file = fileInput.files && fileInput.files[0];
    if (!file) return;
    btnUpload.disabled = true;
    btnUpload.textContent = "提交中...";
    try {
      await uploadFile(file);
      btnUpload.textContent = "上传文件";
    } catch (err) {
      alert("上传异常: " + (err.message || err));
      btnUpload.textContent = "上传文件";
    } finally {
      btnUpload.disabled = false;
      fileInput.value = "";
    }
  });

  btnSend.addEventListener("click", sendMessage);

  chatInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  btnNewSession.addEventListener("click", async function () {
    localStorage.removeItem("rag_session_id");
    sessionId = "";
    chatMessages.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.id = "empty-state";
    empty.innerHTML =
      "<strong>开始提问</strong>可询问员工手册、休假制度、新材料产品规范等内容。系统将按需检索知识库并流式生成回答。";
    chatMessages.appendChild(empty);
    setMobilePanel("chat");
    showToast("已开启新对话");
    try {
      await ensureSession();
    } catch (err) {
      alert(err.message || "新建会话失败");
    }
  });

  if (mobileTabs) {
    mobileTabs.addEventListener("click", function (e) {
      const btn = e.target.closest(".mobile-tab");
      if (!btn) return;
      setMobilePanel(btn.getAttribute("data-panel"));
    });
  }

  // 窄屏默认进入问答区
  if (window.matchMedia && window.matchMedia("(max-width: 900px)").matches) {
    setMobilePanel("chat");
  }

  btnLogout.addEventListener("click", async function () {
    try {
      await RAGApp.apiFetch("/auth/logout", { method: "POST" });
    } catch (err) {
      /* 忽略网络错误，本地仍清理 */
    }
    RAGApp.clearAuth();
    localStorage.removeItem("rag_session_id");
    location.href = "/login";
  });

  // 初始化
  ensureSession().catch(function () {});
  refreshDocuments();
})();