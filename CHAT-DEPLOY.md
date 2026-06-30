# GitHub Pages — THz Lab PI Chat

靜態站由 `docs/` 部署；LLM API 由 Cloudflare Worker 代理（Groq）。

## 本機建置

```powershell
C:\ProgramData\anaconda3\python.exe scripts/build_web_chat.py --lite-prompt --no-rag --api-url "http://127.0.0.1:8787/v1/chat"
C:\ProgramData\anaconda3\python.exe scripts/serve_docs.py --port 8769
```

## GitHub Pages

1. Repo **Settings → Pages → Source: GitHub Actions**
2. 一鍵設定 API（推薦）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_chat_api.ps1
```

或手動：
3. **Settings → Secrets → Actions**：
   - `CHAT_API_URL` — Worker 完整 URL（例 `https://em-lab-pi-chat.workers.dev/v1/chat`）
   - `TURNSTILE_SITE_KEY`（可選）
4. Push 到 `main` 觸發 `.github/workflows/deploy-pages.yml`

**注意**：正式站已關閉 RAG 檢索（`--no-rag`），以控制 API token 用量。

## Cloudflare Worker

```bash
cd worker
npm install -D wrangler
npx wrangler login
npx wrangler secret put GROQ_API_KEY

# wrangler.toml [vars] ALLOWED_ORIGINS 加入 GitHub Pages 網址，例如：
# ALLOWED_ORIGINS = "https://b95901149.github.io"

npx wrangler deploy
```

## 個人網頁連結

```html
<a href="https://b95901149.github.io/em-lab-pi-chat/?sansha=1" target="_blank" rel="noopener">
  THz 實驗室 PI 對話（三思模式）
</a>
```
