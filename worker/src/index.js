/**
 * LLM API proxy for THz Lab PI chat (Cloudflare Worker).
 *
 * Secrets (wrangler secret put):
 *   GROQ_API_KEY      — Groq (OpenAI-compatible)
 *   GEMINI_API_KEY    — Google Gemini (optional fallback)
 *   TURNSTILE_SECRET_KEY  (optional)
 *
 * Env vars in wrangler.toml:
 *   LLM_PROVIDER — "groq" (default) or "gemini"
 *   GROQ_MODEL — default llama-3.3-70b-versatile
 *   GEMINI_MODEL — default gemini-2.0-flash-lite
 *   ALLOWED_ORIGINS — comma-separated origins
 *   DAILY_IP_LIMIT — default 30
 *   GLOBAL_DAILY_LIMIT — default 800
 */

const DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile";
const DEFAULT_GEMINI_MODEL = "gemini-2.0-flash-lite";
const GROQ_BASE = "https://api.groq.com/openai/v1/chat/completions";
const GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models";

export default {
  async fetch(request, env) {
    const cors = buildCors(request, env);

    if (request.method === "OPTIONS") {
      return cors(new Response(null, { status: 204 }));
    }

    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/health") {
      const provider = getProvider(env);
      return cors(
        json({
          ok: true,
          service: "em-lab-pi-chat",
          provider,
          model: getModel(env, provider),
        }),
      );
    }

    if (request.method !== "POST" || url.pathname !== "/v1/chat") {
      return cors(json({ error: "Not found" }, 404));
    }

    const origin = request.headers.get("Origin") || "";
    if (!isOriginAllowed(origin, env)) {
      return cors(json({ error: "Origin not allowed", origin }, 403));
    }

    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    const provider = getProvider(env);

    try {
      const rate = await checkRateLimit(ip, env);
      if (!rate.ok) {
        return cors(json({ error: rate.message }, rate.status));
      }

      const body = await request.json();
      const turnstileOk = await verifyTurnstile(body.turnstileToken, ip, env);
      if (!turnstileOk) {
        return cors(json({ error: "Turnstile verification failed" }, 403));
      }

      const configErr = checkProviderConfig(env, provider);
      if (configErr) {
        return cors(json({ error: configErr }, 503));
      }

      const reply = await callLlmWithRetry(body, env, provider);
      await incrementRateLimit(ip, env);
      return cors(json({ reply }));
    } catch (err) {
      console.error(err);
      const msg = err.message || "Internal error";
      const isQuota = err.status === 429 || /429|quota|TooManyRequests|rate limit/i.test(msg);
      const isAuth =
        err.status === 401 || /invalid api key|unauthorized|authentication/i.test(msg);
      const status = isQuota ? 429 : isAuth ? 401 : 500;
      const label = provider === "groq" ? "Groq" : "Gemini";
      const retryAfterSeconds =
        err.retryAfterSeconds ?? parseRetryAfterSeconds(null, msg) ?? undefined;
      const body = isQuota
        ? {
            error: retryAfterSeconds
              ? `${label} 速率限制，請約 ${retryAfterSeconds} 秒後再試。`
              : `${label} 免費配額已用完或觸發速率限制，請稍後再試。`,
            ...(retryAfterSeconds != null ? { retryAfterSeconds } : {}),
          }
        : isAuth
          ? {
              error:
                err.message ||
                `${label} API 金鑰無效。請更新 Worker 上的 GROQ_API_KEY。`,
            }
          : { error: msg };
      return cors(json(body, status));
    }
  },
};

function getProvider(env) {
  return (env.LLM_PROVIDER || "groq").toLowerCase().trim();
}

function getModel(env, provider) {
  if (provider === "groq") return env.GROQ_MODEL || DEFAULT_GROQ_MODEL;
  return env.GEMINI_MODEL || DEFAULT_GEMINI_MODEL;
}

function checkProviderConfig(env, provider) {
  if (provider === "groq") {
    if (!env.GROQ_API_KEY) return "Server misconfigured: missing GROQ_API_KEY";
    return null;
  }
  if (provider === "gemini") {
    if (!env.GEMINI_API_KEY) return "Server misconfigured: missing GEMINI_API_KEY";
    return null;
  }
  return `Unknown LLM_PROVIDER: ${provider} (use groq or gemini)`;
}

async function callLlmWithRetry(body, env, provider, maxRetries = 3) {
  let delay = 600;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await callLlm(body, env, provider);
    } catch (err) {
      const isRate =
        err.status === 429 ||
        /429|rate limit|TooManyRequests|tokens per minute/i.test(err.message || "");
      // 429：立即回傳等待秒數，避免 Worker 在後台重試導致前端逾時
      if (isRate) throw err;
      if (attempt === maxRetries) throw err;
      await sleep(delay);
      delay = Math.min(delay * 2, 8000);
    }
  }
  throw new Error("LLM retry exhausted");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function callLlm(body, env, provider) {
  if (provider === "groq") return callGroq(body, env);
  if (provider === "gemini") return callGemini(body, env);
  throw new Error(`Unknown LLM_PROVIDER: ${provider}`);
}

async function callGroq(body, env) {
  const model = env.GROQ_MODEL || DEFAULT_GROQ_MODEL;
  const messages = [];

  const system = body.systemInstruction || "";
  if (system) {
    messages.push({ role: "system", content: system });
  }

  for (const msg of body.messages || []) {
    const role = msg.role === "assistant" ? "assistant" : "user";
    messages.push({ role, content: msg.content });
  }

  const res = await fetch(GROQ_BASE, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${env.GROQ_API_KEY}`,
    },
    body: JSON.stringify({
      model,
      messages,
      temperature: 0.7,
      max_tokens: Math.min(Number(body.maxTokens) || 4096, 4096),
    }),
  });

  const data = await res.json();
  if (!res.ok) {
    const msg = data?.error?.message || JSON.stringify(data);
    const err = new Error(msg);
    if (res.status === 401 || /invalid api key/i.test(msg)) {
      err.status = 401;
      err.message =
        "Groq API 金鑰無效或已撤銷。請到 console.groq.com 建立新金鑰，並執行 scripts/sync_groq_secret.py";
    }
    if (res.status === 429) {
      err.status = 429;
      err.retryAfterSeconds = parseRetryAfterSeconds(res, msg);
    }
    throw err;
  }

  const text = (data?.choices?.[0]?.message?.content || "").trim();
  if (!text) throw new Error("Groq returned empty response");
  return text;
}

/** Parse Groq / OpenAI-style retry wait from headers or error message. */
function parseRetryAfterSeconds(res, message = "") {
  const hdr = res?.headers?.get?.("retry-after");
  if (hdr) {
    const n = parseFloat(hdr);
    if (!Number.isNaN(n) && n > 0) return Math.ceil(n);
  }

  const m = String(message);
  let match = m.match(/try again in\s+([\d.]+)\s*s(?:ec(?:ond)?s?)?/i);
  if (match) return Math.ceil(parseFloat(match[1]));
  match = m.match(/retry(?:\s+after)?\s+([\d.]+)\s*(?:s|sec(?:ond)?s?)?/i);
  if (match) return Math.ceil(parseFloat(match[1]));
  match = m.match(/wait\s+([\d.]+)\s*(?:s|sec(?:ond)?s?)/i);
  if (match) return Math.ceil(parseFloat(match[1]));
  return null;
}

async function callGemini(body, env) {
  const model = env.GEMINI_MODEL || DEFAULT_GEMINI_MODEL;
  const url = `${GEMINI_BASE}/${encodeURIComponent(model)}:generateContent?key=${env.GEMINI_API_KEY}`;

  const contents = [];
  for (const msg of body.messages || []) {
    const role = msg.role === "assistant" ? "model" : "user";
    contents.push({ role, parts: [{ text: msg.content }] });
  }

  const payload = {
    systemInstruction: {
      parts: [{ text: body.systemInstruction || "" }],
    },
    contents,
    generationConfig: {
      temperature: 0.7,
      maxOutputTokens: 4096,
    },
  };

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await res.json();
  if (!res.ok) {
    const msg = data?.error?.message || JSON.stringify(data);
    const err = new Error(msg);
    if (res.status === 429 || data?.error?.code === 429) err.status = 429;
    throw err;
  }

  const parts = data?.candidates?.[0]?.content?.parts || [];
  const text = parts.map((p) => p.text || "").join("").trim();
  if (!text) throw new Error("Gemini returned empty response");
  return text;
}

function buildCors(request, env) {
  const origin = request.headers.get("Origin") || "";
  const allowed = isOriginAllowed(origin, env) ? origin : "";
  const headers = {
    "Access-Control-Allow-Origin": allowed || "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
  };
  return (response) => {
    const r = new Response(response.body, response);
    Object.entries(headers).forEach(([k, v]) => r.headers.set(k, v));
    return r;
  };
}

function isOriginAllowed(origin, env) {
  if (!origin) return true;
  const list = (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
  if (list.length === 0) return true;
  return list.some((o) => origin === o || origin.startsWith(o));
}

async function verifyTurnstile(token, ip, env) {
  if (!env.TURNSTILE_SECRET_KEY) return true;
  if (!token) return false;
  const form = new FormData();
  form.append("secret", env.TURNSTILE_SECRET_KEY);
  form.append("response", token);
  form.append("remoteip", ip);
  const res = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
    method: "POST",
    body: form,
  });
  const data = await res.json();
  return data.success === true;
}

async function checkRateLimit(ip, env) {
  const dailyIpLimit = parseInt(env.DAILY_IP_LIMIT || "30", 10);
  const globalLimit = parseInt(env.GLOBAL_DAILY_LIMIT || "800", 10);
  const today = new Date().toISOString().slice(0, 10);

  if (env.RATE_KV) {
    const ipKey = `ip:${ip}:${today}`;
    const globalKey = `global:${today}`;
    const [ipCount, globalCount] = await Promise.all([
      env.RATE_KV.get(ipKey),
      env.RATE_KV.get(globalKey),
    ]);
    if (parseInt(ipCount || "0", 10) >= dailyIpLimit) {
      return { ok: false, status: 429, message: "此 IP 今日配額已用完，請明天再試。" };
    }
    if (parseInt(globalCount || "0", 10) >= globalLimit) {
      return { ok: false, status: 503, message: "服務今日總配額已滿，請明天再試。" };
    }
  }

  return { ok: true };
}

async function incrementRateLimit(ip, env) {
  if (!env.RATE_KV) return;
  const today = new Date().toISOString().slice(0, 10);
  const ipKey = `ip:${ip}:${today}`;
  const globalKey = `global:${today}`;

  const ipCount = parseInt((await env.RATE_KV.get(ipKey)) || "0", 10);
  const globalCount = parseInt((await env.RATE_KV.get(globalKey)) || "0", 10);

  await env.RATE_KV.put(ipKey, String(ipCount + 1), { expirationTtl: 86400 });
  await env.RATE_KV.put(globalKey, String(globalCount + 1), { expirationTtl: 86400 });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}
