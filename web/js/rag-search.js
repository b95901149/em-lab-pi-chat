/** Client-side RAG search (BM25-lite) over prebuilt chunks. */

let _chunks = null;
let _searchIndex = null;
let _manifest = null;

const SERIES_KEYWORDS = {
  line: [
    "deadline", "遲交", "提前", "確認", "聯繫", "細節", "差強人意", "不懂要問",
    "量測", "口試", "天線", "報告", "投影片", "行政", "實驗室", "你各位",
    "checklist", "三思", "防腦殘", "對空氣講話",
  ],
  em: ["電磁", "maxwell", "電場", "磁場", "波動", "向量", "散度", "旋度", "poynting", "邊界", "靜電", "靜磁"],
  fourier_optics: ["傅立葉", "繞射", "透鏡", "4f", "角譜", "全息", "光學", "fresnel"],
  fourier_optics_lab: ["光路", "michelson", "實驗", "光學元件", "2f", "4f"],
  rf_microwave: ["微波", "天線", "smith", "傳輸線", "濾波器", "hfss", "匹配", "ghz", "vna", "catr"],
  radio_life: ["生活", "電波", "wifi", "gps", "微波爐", "安全", "輻射"],
  research: ["thz", "太赫茲", "研究", "論文", "讀博", "lab", "實驗室", "方向", "口試"],
};

export async function loadRag(baseUrl = "") {
  const prefix = baseUrl.replace(/\/?$/, "/");
  const [chunks, searchIndex, manifest] = await Promise.all([
    fetch(`${prefix}rag/chunks.json`).then((r) => {
      if (!r.ok) throw new Error("無法載入 RAG chunks");
      return r.json();
    }),
    fetch(`${prefix}rag/search-index.json`).then((r) => {
      if (!r.ok) throw new Error("無法載入 search index");
      return r.json();
    }),
    fetch(`${prefix}rag/manifest.json`).then((r) => r.json()).catch(() => ({})),
  ]);
  _chunks = chunks;
  _searchIndex = searchIndex;
  _manifest = manifest;
  return { chunkCount: chunks.length, manifest };
}

function tokenize(text) {
  const lower = text.toLowerCase();
  const tokens = [];
  for (const w of lower.match(/[a-z0-9][a-z0-9._-]{1,}/g) || []) {
    if (w.length >= 2) tokens.push(w);
  }
  const cjk = lower.replace(/[^\u4e00-\u9fff]/g, "");
  for (let i = 0; i < cjk.length; i++) {
    tokens.push(cjk[i]);
    if (i + 1 < cjk.length) tokens.push(cjk.slice(i, i + 2));
  }
  return tokens;
}

function detectCourses(query) {
  const q = query.toLowerCase();
  const scores = {};
  for (const [course, kws] of Object.entries(SERIES_KEYWORDS)) {
    scores[course] = kws.filter((k) => q.includes(k.toLowerCase())).length;
  }
  const best = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  if (best[0][1] > 0) return best.filter(([, s]) => s > 0).map(([c]) => c);
  return null;
}

function chunkAllowed(chunk, opts) {
  if (chunk.source === "line" && opts.line === false) return false;
  if (chunk.source === "transcript" && !opts.teaching) return false;
  if ((chunk.source === "research" || chunk.source === "publications") && !opts.research) return false;
  return true;
}

export function search(query, topK = 5, opts = { line: true, teaching: true, research: true }) {
  if (!_chunks || !_searchIndex) return [];

  const minScore = opts.minScore ?? 0;
  const lineBoost = opts.lineBoost ?? 1.25;
  const qTokens = [...new Set(tokenize(query))];
  const courses = detectCourses(query);
  const { idf, inverted } = _searchIndex;
  const scores = new Map();

  for (const term of qTokens) {
    const ids = inverted[term];
    if (!ids) continue;
    const weight = idf[term] || 0.5;
    for (const id of ids) {
      scores.set(id, (scores.get(id) || 0) + weight);
    }
  }

  const ranked = [...scores.entries()]
    .map(([id, score]) => {
      const chunk = _chunks.find((c) => c.id === id);
      if (!chunk || !chunkAllowed(chunk, opts)) return null;
      if (courses && chunk.source === "transcript" && !courses.includes(chunk.course)) {
        return { chunk, score: score * 0.35 };
      }
      if (chunk.source === "line" && opts.line !== false) {
        return { chunk, score: score * lineBoost };
      }
      return { chunk, score };
    })
    .filter(Boolean)
    .sort((a, b) => b.score - a.score);

  if (ranked.length === 0) {
    if (minScore > 0) return [];
    const fallback = _chunks
      .filter((c) => chunkAllowed(c, opts))
      .filter((c) => !courses || c.source !== "transcript" || courses.includes(c.course))
      .sort((a, b) => (b.source === "line" ? 1 : 0) - (a.source === "line" ? 1 : 0))
      .slice(0, topK)
      .map((chunk) => ({ chunk, score: 0 }));
    return fallback;
  }

  return ranked.filter((h) => h.score >= minScore).slice(0, topK);
}

function truncateText(text, maxChars) {
  if (!maxChars || text.length <= maxChars) return text;
  return `${text.slice(0, maxChars).trim()}…`;
}

export function formatContext(hits, limits = {}) {
  if (!hits.length) return "";
  const maxChunk = limits.maxChunkChars || 0;
  const maxTotal = limits.maxContextChars || 0;
  const parts = [];
  let total = 0;

  for (let i = 0; i < hits.length; i++) {
    const { chunk } = hits[i];
    const label = chunk.course_label || chunk.course;
    const title = chunk.title || "參考";
    const body = truncateText(chunk.text, maxChunk);
    const block = `[${i + 1}] (${label}) ${title}\n${body}`;
    if (maxTotal && total + block.length > maxTotal) {
      if (parts.length === 0) {
        parts.push(truncateText(block, maxTotal));
      }
      break;
    }
    parts.push(block);
    total += block.length;
  }

  return parts.join("\n\n---\n\n");
}

export function formatRefs(hits) {
  const seen = new Set();
  const refs = [];
  for (const { chunk } of hits) {
    const key = chunk.url || chunk.id;
    if (seen.has(key)) continue;
    seen.add(key);
    refs.push({
      title: chunk.title,
      url: chunk.url,
      course: chunk.course_label || chunk.course,
    });
  }
  return refs;
}
