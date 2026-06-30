import { loadRag, search, formatContext, formatRefs } from "./rag-search.js";
import { renderMarkdown } from "./markdown-lite.js";

const STORAGE_SANSHA = "emLabPi_sansha";
const STORAGE_DISCLAIMER = "emLabPi_disclaimerShown";

const WELCOME_CARDS = [
  { tag: "頻譜", title: "THz 研究定位", q: "太赫茲在頻譜上站哪裡？適合做什麼研究？" },
  { tag: "天線", title: "300 GHz 入門", q: "我想做 300 GHz 天線研究，該從哪裡開始？" },
  { tag: "口試", title: "口試準備", q: "下個月口試，有哪些要注意？" },
  { tag: "量測", title: "量測 checklist", q: "明天要跟老師量天線，今天該準備什麼？" },
];

const els = {
  messages: document.getElementById("messages"),
  welcome: document.getElementById("welcome"),
  welcomeGrid: document.getElementById("welcome-grid"),
  refs: document.getElementById("refs"),
  form: document.getElementById("chat-form"),
  input: document.getElementById("user-input"),
  send: document.getElementById("btn-send"),
  sanshaToggle: document.getElementById("sansha-toggle"),
  sanshaBadge: document.getElementById("sansha-badge"),
  sidePanel: document.getElementById("side-panel"),
  overlay: document.getElementById("overlay"),
  btnPanel: document.getElementById("btn-panel"),
  btnClear: document.getElementById("btn-clear"),
  ragTeaching: document.getElementById("rag-teaching"),
  ragResearch: document.getElementById("rag-research"),
  ragLine: document.getElementById("rag-line"),
  ragSection: document.getElementById("rag-section"),
  siteSubtitle: document.getElementById("site-subtitle"),
  statusPill: document.getElementById("status-pill"),
  commandCenter: document.getElementById("command-center"),
  turnstileWrap: document.getElementById("turnstile-wrap"),
  layout: document.querySelector(".layout"),
  chatPanel: document.querySelector(".chat-panel"),
};

let config = {};
let systemPrompt = "";
let history = [];
let turnstileWidgetId = null;
let busy = false;
let assetsReady = false;
let assetsError = "";
let lastRequestAt = 0;
let backoffUntil = 0;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function basePath() {
  const path = window.location.pathname;
  if (path.endsWith("/")) return path;
  const idx = path.lastIndexOf("/");
  return idx >= 0 ? path.slice(0, idx + 1) : "/";
}

function fetchWithTimeout(url, ms = 12000, options = {}) {
  if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
    return fetch(url, { ...options, signal: AbortSignal.timeout(ms) });
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  return fetch(url, { ...options, signal: ctrl.signal }).finally(() => clearTimeout(timer));
}

async function fetchText(url, ms = 12000) {
  const res = await fetchWithTimeout(url, ms);
  if (!res.ok) throw new Error(`無法載入 ${url} (HTTP ${res.status})`);
  return res.text();
}

async function loadAssets() {
  const base = basePath();
  const [cfgText, promptText] = await Promise.all([
    fetchText(`${base}config.json`),
    fetchText(`${base}assets/system-prompt.txt`),
  ]);
  config = JSON.parse(cfgText);
  systemPrompt = promptText;
  if (config.ragEnabled !== false) {
    await loadRag(base);
  }
}

function setStatus(state, text) {
  const pill = document.getElementById("status-pill");
  if (!pill) return;
  pill.textContent = text;
  pill.classList.remove("ready", "error");
  if (state) pill.classList.add(state);
  if (typeof window.__setStatusPill === "function") {
    window.__setStatusPill(text, state);
  }
}

function applyLiteMode() {
  if (!config.liteMode) return;
  const ragOn = config.ragEnabled !== false;
  if (els.siteSubtitle) {
    els.siteSubtitle.textContent = ragOn ? "Lite · 公開去識別 + RAG" : "Lite · 公開去識別版";
  }
  if (ragOn) {
    els.ragSection?.classList.remove("hidden");
    if (els.ragLine && config.ragLineDefault !== undefined) {
      els.ragLine.checked = config.ragLineDefault;
    }
    if (els.ragTeaching && config.ragTeachingDefault !== undefined) {
      els.ragTeaching.checked = config.ragTeachingDefault;
    }
    if (els.ragResearch && config.ragResearchDefault !== undefined) {
      els.ragResearch.checked = config.ragResearchDefault;
    }
  } else {
    els.ragSection?.classList.add("hidden");
    if (els.ragTeaching) els.ragTeaching.checked = false;
    if (els.ragResearch) els.ragResearch.checked = false;
  }
}

function shouldAttachRag(text) {
  if (config.ragEnabled === false) return false;
  const q = text.trim();
  if (!q) return false;
  if (q.length < (config.ragMinQueryLen || 4)) return false;
  if (config.skipRagGreeting && /^(你好|您好|嗨|hi|hello|謝謝|谢谢|早安|晚安|哈囉)[!！。.?\s]*$/i.test(q)) {
    return false;
  }
  return true;
}

function resolveRagHits(text) {
  if (!shouldAttachRag(text)) return [];
  const ragOpts = {
    line: els.ragLine ? els.ragLine.checked : config.ragLineDefault !== false,
    teaching: els.ragTeaching ? els.ragTeaching.checked : config.ragTeachingDefault === true,
    research: els.ragResearch ? els.ragResearch.checked : config.ragResearchDefault === true,
    minScore: config.ragMinScore ?? 0,
    lineBoost: config.ragLineBoost ?? 1.25,
  };
  return search(text, config.ragTopK || 5, ragOpts);
}

async function fetchChatWithBackoff(apiUrl, body) {
  const maxRetries = config.apiMaxRetries ?? 2;
  const baseMs = config.apiBackoffBaseMs ?? 1000;
  const minGap = config.minRequestIntervalMs ?? 0;
  const requestTimeoutMs = config.apiRequestTimeoutMs ?? 180000;
  const now = Date.now();

  if (now < backoffUntil) {
    const waitSec = Math.ceil((backoffUntil - now) / 1000);
    throw new Error(`API 速率限制中，請 ${waitSec} 秒後再試`);
  }
  if (minGap > 0 && now - lastRequestAt < minGap) {
    await sleep(minGap - (now - lastRequestAt));
  }

  let lastError = null;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    lastRequestAt = Date.now();
    const res = await fetchWithTimeout(apiUrl, requestTimeoutMs, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));

    if (res.status === 429) {
      const retrySec =
        typeof data.retryAfterSeconds === "number" && data.retryAfterSeconds > 0
          ? Math.ceil(data.retryAfterSeconds)
          : null;
      const wait = retrySec ? retrySec * 1000 : Math.min(30000, baseMs * 2 ** attempt);
      backoffUntil = Date.now() + wait;
      const err = new Error(data.error || data.message || "HTTP 429");
      err.retryAfterSeconds = retrySec;
      lastError = err;
      if (attempt < maxRetries) {
        await sleep(wait);
        continue;
      }
      throw lastError;
    }

    if (!res.ok) {
      throw new Error(data.error || data.message || `HTTP ${res.status}`);
    }

    backoffUntil = 0;
    return data;
  }

  throw lastError || new Error("API 請求失敗");
}

function ragContextLimits() {
  return {
    maxChunkChars: config.ragMaxChunkChars || 0,
    maxContextChars: config.ragMaxContextChars || 0,
  };
}

function healthUrlFromApi(apiUrl) {
  const resolved = resolveApiUrl(apiUrl || "");
  return resolved.replace(/\/v1\/chat\/?$/i, "/health");
}

async function probeApi() {
  if (!config.apiUrl) {
    setStatus("error", "未設定 API");
    return false;
  }
  try {
    const res = await fetchWithTimeout(healthUrlFromApi(config.apiUrl), 8000);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const label = (data.provider || "api").toUpperCase();
    setStatus("ready", `${label} 就緒`);
    return true;
  } catch (err) {
    console.warn("API probe failed:", err);
    setStatus("error", "API 離線");
    return false;
  }
}

function readSanshaFromUrl() {
  const p = new URLSearchParams(window.location.search);
  if (p.get("sansha") === "1" || p.get("sansha") === "true") return true;
  return localStorage.getItem(STORAGE_SANSHA) === "1";
}

function setSansha(on) {
  if (els.sanshaToggle) els.sanshaToggle.checked = on;
  els.sidePanel?.classList.toggle("sansha-on", on);
  els.sanshaBadge?.classList.toggle("hidden", !on);
  localStorage.setItem(STORAGE_SANSHA, on ? "1" : "0");
}

function updateWelcome() {
  const hasUserChat = history.some((m) => m.role === "user");
  if (els.welcome) els.welcome.hidden = hasUserChat;
}

function labelForRole(role) {
  if (role === "user") return "你";
  if (role === "assistant") return "PI";
  return "系統";
}

function scrollChatToBottom() {
  const root = els.chatPanel || els.layout;
  if (root) {
    root.scrollTo({ top: root.scrollHeight, behavior: "smooth" });
    return;
  }
  if (els.messages) {
    els.messages.scrollTop = els.messages.scrollHeight;
  }
}

function appendMessage(role, content, extraClass = "") {
  const wrap = document.createElement("div");
  wrap.className = `msg-wrap ${role}`.trim();

  const label = document.createElement("div");
  label.className = "msg-label";
  label.textContent = labelForRole(role);
  wrap.appendChild(label);

  const div = document.createElement("div");
  div.className = `msg ${role} ${extraClass}`.trim();
  if (role === "assistant" && !extraClass.includes("error")) {
    div.innerHTML = renderMarkdown(content);
  } else {
    div.textContent = content;
  }
  wrap.appendChild(div);

  els.messages.appendChild(wrap);
  scrollChatToBottom();
  updateWelcome();
  return div;
}

function friendlyApiError(message = "", { retryAfterSeconds = null } = {}) {
  const m = String(message);
  const waitSec =
    retryAfterSeconds > 0
      ? Math.ceil(retryAfterSeconds)
      : parseRetryAfterFromMessage(m);

  if (/Failed to fetch|NetworkError|Load failed|fetch/i.test(m)) {
    return "⚠ 無法連線到 API。請確認 Worker 已啟動（wrangler dev --port 8787），並用 http://127.0.0.1:8769/ 開啟。";
  }
  if (/AbortError|TimeoutError|signal timed out|逾時|timeout/i.test(m)) {
    return (
      "⚠ 請求逾時（模型回覆較久，或剛觸發 Groq 速率限制）。\n" +
      "請稍後再試，或將問題拆短一些。"
    );
  }
  if (/invalid api key|unauthorized|authentication|金鑰無效|GROQ_API_KEY/i.test(m)) {
    return (
      "⚠ Groq API 金鑰無效或已撤銷。\n" +
      "請到 https://console.groq.com/keys 建立新金鑰，\n" +
      "更新 worker/.dev.vars 後執行：\n" +
      "C:\\ProgramData\\anaconda3\\python.exe scripts\\sync_groq_secret.py"
    );
  }
  if (/429|quota|TooManyRequests|配額|rate limit|速率限制|tokens per minute/i.test(m)) {
    if (waitSec) {
      return (
        `⚠ API 觸發速率限制（Groq）。\n` +
        `請等待約 ${waitSec} 秒後再試。\n` +
        "也可到 Groq 控制台查看 TPM 用量。"
      );
    }
    return (
      "⚠ API 免費配額已用完或觸發速率限制。\n" +
      "請稍後再試，或到 Groq / AI Studio 查看用量與金鑰設定。"
    );
  }
  if (m.length > 280) return `⚠ ${m.slice(0, 280)}…`;
  return m ? `⚠ ${m}` : "⚠ 伺服器未回傳內容，請稍後再試。";
}

function parseRetryAfterFromMessage(message = "") {
  const m = String(message);
  let match = m.match(/(?:約|等待約?|wait)\s*([\d.]+)\s*秒/i);
  if (match) return Math.ceil(parseFloat(match[1]));
  match = m.match(/try again in\s+([\d.]+)\s*s/i);
  if (match) return Math.ceil(parseFloat(match[1]));
  return null;
}

function showRefs(refs) {
  if (!refs.length) {
    els.refs.classList.add("hidden");
    return;
  }
  els.refs.classList.remove("hidden");
  els.refs.innerHTML =
    "<strong>參考：</strong> " +
    refs
      .map((r) => {
        if (r.url) {
          return `<a href="${r.url}" target="_blank" rel="noopener">${escapeHtml(r.title || r.course)}</a>`;
        }
        return escapeHtml(r.title || r.course);
      })
      .join("");
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function buildSanshaInstruction() {
  return (
    "\n\n【三思模式已開啟】使用者下達任務或指令時，回覆必須先附「三思 Checklist」" +
    "（一思·釐清、二思·驗證、三思·交付、本任務特別注意），格式同 SKILL 範例；" +
    "再給正式回答。Checklist 項目要具體可勾選。純知識解釋題可省略 Checklist。"
  );
}

function isTaskLike(q) {
  return /準備|checklist|口試|量測|deadline|交|寄信|模擬|論文|明天|下週|注意|清单|清單|三思/i.test(q);
}

function autoResizeInput() {
  const ta = els.input;
  ta.style.height = "auto";
  ta.style.height = `${Math.min(ta.scrollHeight, 140)}px`;
}

function handleFormSubmit(e) {
  e.preventDefault();
  const text = els.input?.value ?? "";
  if (els.input) {
    els.input.value = "";
    autoResizeInput();
  }
  if (!assetsReady) {
    if (text.trim()) {
      appendMessage(
        "system",
        assetsError
          ? `載入失敗：${assetsError}`
          : "仍在載入設定，請稍候幾秒後再試。",
        "error",
      );
      if (els.input) {
        els.input.value = text;
        autoResizeInput();
      }
    }
    return;
  }
  sendMessage(text);
}

async function sendMessage(text) {
  if (busy || !text.trim()) return;
  busy = true;
  let typing = null;
  try {
    if (els.send) els.send.disabled = true;
    els.commandCenter?.classList.add("is-thinking");

    appendMessage("user", text.trim());
    history.push({ role: "user", content: text.trim() });

    typing = appendMessage("assistant", "思考中…", "typing");
    const hits = resolveRagHits(text);
    const ragContext = formatContext(hits, ragContextLimits());
    const refs = formatRefs(hits);

    let sys = systemPrompt;
    if (els.sanshaToggle.checked && isTaskLike(text)) {
      sys += buildSanshaInstruction();
    }
    if (ragContext) {
      sys += `\n\n[參考資料 — 檢索結果]\n${ragContext}`;
    }

    const body = {
      systemInstruction: sys,
      messages: history.slice(-(config.maxHistoryTurns || 10) * 2),
      sanshaMode: els.sanshaToggle.checked,
      maxTokens: config.maxOutputTokens || undefined,
    };

    if (config.turnstileSiteKey && window.turnstile) {
      const token = window.turnstile.getResponse(turnstileWidgetId);
      if (!token) {
        throw new Error("請先完成人機驗證（Turnstile）");
      }
      body.turnstileToken = token;
    }

    const apiUrl = resolveApiUrl(config.apiUrl);
    const data = await fetchChatWithBackoff(apiUrl, body);

    const reply = (data.reply || data.text || "").trim();
    typing?.remove();
    if (!reply) {
      throw new Error("伺服器回傳空白內容");
    }
    appendMessage("assistant", reply);
    history.push({ role: "assistant", content: reply });
    showRefs(refs);

    if (config.turnstileSiteKey && window.turnstile) {
      window.turnstile.reset(turnstileWidgetId);
    }
  } catch (err) {
    typing?.remove();
    const msg =
      err?.name === "AbortError" || err?.name === "TimeoutError"
        ? "請求逾時"
        : err.message || String(err);
    appendMessage(
      "assistant",
      friendlyApiError(msg, { retryAfterSeconds: err?.retryAfterSeconds }),
      "error",
    );
  } finally {
    busy = false;
    if (els.send) els.send.disabled = false;
    els.commandCenter?.classList.remove("is-thinking");
    els.input?.focus();
    autoResizeInput();
  }
}

function resolveApiUrl(apiUrl) {
  if (!apiUrl || apiUrl.startsWith("/")) {
    const origin = window.location.origin;
    return origin + (apiUrl || "/api/v1/chat");
  }
  return apiUrl;
}

function setupTurnstile() {
  if (!config.turnstileSiteKey || !window.turnstile) return;
  els.turnstileWrap.classList.remove("hidden");
  turnstileWidgetId = window.turnstile.render(els.turnstileWrap, {
    sitekey: config.turnstileSiteKey,
    theme: "dark",
  });
}

function setupWelcomeGrid() {
  if (!els.welcomeGrid) return;
  els.welcomeGrid.innerHTML = "";
  for (const card of WELCOME_CARDS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "welcome-card";
    btn.innerHTML = `<strong>${escapeHtml(card.tag)}</strong>${escapeHtml(card.title)}`;
    btn.addEventListener("click", () => {
      els.input.value = card.q;
      autoResizeInput();
      els.input.focus();
      closeMobilePanel();
    });
    els.welcomeGrid.appendChild(btn);
  }
}

function setupQuickButtons() {
  document.querySelectorAll(".quick-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const q = btn.getAttribute("data-q") || "";
      els.input.value = q;
      autoResizeInput();
      els.input.focus();
      closeMobilePanel();
    });
  });
}

function setupMobilePanel() {
  els.btnPanel?.addEventListener("click", () => {
    els.sidePanel.classList.add("open");
    els.overlay.classList.remove("hidden");
    els.overlay.classList.add("open");
  });
  els.overlay?.addEventListener("click", closeMobilePanel);
}

function closeMobilePanel() {
  els.sidePanel.classList.remove("open");
  els.overlay.classList.add("hidden");
  els.overlay.classList.remove("open");
}

function setupComposer() {
  if (!els.input) return;
  els.input.addEventListener("input", autoResizeInput);
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!busy && els.input.value.trim()) {
        els.form?.requestSubmit();
      }
    }
  });
}

function bindFormEarly() {
  els.form?.addEventListener("submit", handleFormSubmit);
}

async function init() {
  bindFormEarly();
  setupWelcomeGrid();
  setupComposer();

  try {
    await loadAssets();
    applyLiteMode();
    await probeApi();
    assetsReady = true;
  } catch (err) {
    console.error(err);
    assetsError = err.message || String(err);
    setStatus("error", "載入失敗");
    appendMessage(
      "system",
      `載入失敗：${assetsError}。請用 http://127.0.0.1:8769/ 開啟（不要用 file://），並確認已執行 build_web_chat.py。`,
      "error",
    );
    return;
  }

  setSansha(readSanshaFromUrl());
  updateWelcome();

  if (!localStorage.getItem(STORAGE_DISCLAIMER)) {
    localStorage.setItem(STORAGE_DISCLAIMER, "1");
  }

  els.sanshaToggle?.addEventListener("change", () => setSansha(els.sanshaToggle.checked));

  els.btnClear?.addEventListener("click", () => {
    history = [];
    els.messages.innerHTML = "";
    els.refs.classList.add("hidden");
    localStorage.removeItem(STORAGE_DISCLAIMER);
    updateWelcome();
    appendMessage("system", config.disclaimer || "對話已清除。");
    localStorage.setItem(STORAGE_DISCLAIMER, "1");
  });

  setupQuickButtons();
  setupMobilePanel();

  if (window.turnstile) {
    setupTurnstile();
  } else {
    window.addEventListener("load", () => setTimeout(setupTurnstile, 500));
  }

  const prefill = new URLSearchParams(window.location.search).get("q");
  if (prefill) {
    els.input.value = prefill;
    autoResizeInput();
  }
}

init().catch((err) => {
  console.error("init failed:", err);
  setStatus("error", "啟動失敗");
});
