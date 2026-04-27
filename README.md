# Paper Reader MVP

A full-stack MVP for bilingual paper reading:
- Upload `.pdf` or `.tex`
- Parse PDF via the [MinerU](https://mineru.net/apiManage/docs) cloud API (精准解析, Bearer token)
- Left/center/right reading workspace with toggleable Upload / Reader / Chat regions
- Show original and translated PDF side-by-side
- Chat with paper context via OpenAI-compatible API
- Premium interactions: generated-file list, reference preview, and template prompts (Highlight/Baseline/Limitations)

## Project Tree

```text
PaperReader/
├── backend/
│   └── app/
│       ├── api/
│       │   ├── routes_chat.py
│       │   ├── routes_document.py
│       │   └── routes_upload.py
│       ├── core/
│       │   └── config.py
│       ├── models/
│       │   ├── schemas.py
│       │   └── store.py
│       ├── services/
│       │   ├── document_pipeline.py
│       │   ├── latex_service.py
│       │   ├── llm_client.py
│       │   ├── mineru_service.py
│       │   └── translate_service.py
│       ├── workers/
│       │   └── tasks.py
│       └── main.py
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatPanel.tsx
│   │   │   ├── PdfPane.tsx
│   │   │   └── UploadPanel.tsx
│   │   ├── lib/
│   │   │   └── api.ts
│   │   ├── pages/
│   │   │   └── ReaderPage.tsx
│   │   ├── main.tsx
│   │   └── styles.css
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── data/
│   ├── cache/
│   ├── outputs/
│   └── uploads/
├── infra/
│   └── Dockerfile.backend
├── scripts/
│   ├── setup_linux.sh
│   ├── setup_macos.sh
│   └── setup_windows.ps1
├── .env.example
├── docker-compose.yml
├── Makefile
├── plan.md
├── README.md
└── requirements.txt
```

## Python Dependencies (full list)

From `requirements.txt`:

- fastapi==0.115.0
- uvicorn[standard]==0.30.6
- python-multipart==0.0.9
- pydantic==2.9.2
- pydantic-settings==2.5.2
- openai==1.51.2
- requests==2.32.3
- celery==5.4.0
- redis==5.0.8
- httpx==0.27.2
- pytest==8.3.3
- pypdf==4.3.1
- pypdfium2==4.30.0

## Environment Setup

1. Copy environment file:

```bash
cp .env.example .env
```

2. Fill `.env` with your OpenAI-compatible endpoint/key.

### Required variables

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `MINERU_API_KEY` (apply at https://mineru.net/apiManage/docs)

### MinerU PDF parsing

PDF parsing now goes through the MinerU 精准解析 API (no local OCR / GPU /
large model downloads required). Tunables (all optional except the API key):

- `MINERU_API_KEY` — Bearer token from your MinerU account.
- `MINERU_BASE_URL` — defaults to `https://mineru.net/api/v4`.
- `MINERU_MODEL_VERSION` — `vlm` (recommended), `pipeline`, or `MinerU-HTML`.
- `MINERU_LANGUAGE` — `en` for English papers, `ch` for Chinese, etc.
- `MINERU_ENABLE_FORMULA`, `MINERU_ENABLE_TABLE`, `MINERU_IS_OCR` — feature flags.
- `MINERU_POLL_INTERVAL` (seconds), `MINERU_TIMEOUT` (seconds) — polling control.

Limits enforced by MinerU: file ≤ 200 MB, ≤ 200 pages, 1000 high-priority
pages/day per account. Network egress to `mineru.net` and the returned
OSS/CDN hosts must be allowed.

## Local Run (recommended with conda)

Use the project conda env for all commands:

```bash
conda activate d2l
```

### 1. Install dependencies

后端 Python 依赖：

```bash
pip install -r requirements.txt
```

前端 Node 依赖（首次启动或 `package.json` 变更后执行）：

```bash
npm --prefix frontend install
```

如需在升级旧环境后避免二进制/接口不兼容，可强制重装：

```bash
pip install --force-reinstall -r requirements.txt
```

### 2. 启动服务

推荐使用项目根目录下的 Makefile 快捷命令（每条命令请在独立终端中运行）：

```bash
# 终端 1：启动后端 (FastAPI + Uvicorn, 默认 http://localhost:8000)
make backend

# 终端 2：启动前端 (Vite Dev Server, 默认 http://localhost:5173)
make frontend

# 终端 3（可选）：启动 Celery Worker，用于后续异步任务扩展
make worker
```

等价的原始命令：

```bash
# 后端
uvicorn app.main:app --reload --app-dir backend

# 前端
npm --prefix frontend run dev

# Worker（可选）
celery -A app.workers.tasks worker -l info --workdir backend
```

启动后在浏览器打开：<http://localhost:5173>

### 3. 前端构建与预览（可选）

```bash
npm --prefix frontend run build      # 产出 frontend/dist
npm --prefix frontend run preview    # 本地预览生产构建
```

### 4. 常用校验

```bash
pytest                               # 运行后端测试
python -m compileall backend/app     # 快速语法检查
```

> 提示：上传与解析在请求链路中是同步执行的，处理较大 PDF 时前端会持续轮询 `GET /api/document/{id}` 直至 `status` 变为 `done` 或 `failed`。

## Docker Run

```bash
docker compose up --build
```

Services:
- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- Redis: `localhost:6379`

## API Endpoints

- `GET /health`
- `POST /api/upload` (multipart file: `.pdf` or `.tex`)
- `GET /api/documents` — 列出所有文档摘要（用于侧栏文件切换）
- `GET /api/document/{document_id}`
- `POST /api/chat`

### `GET /api/document/{document_id}` response highlights

Now includes:
- `source_filename`
- `artifacts` (uploaded and generated files)
- `references` (extracted bibliography entries for preview)
- plus existing `status`, `original_pdf_url`, `translated_pdf_url`, `logs`

### Chat payload

```json
{
  "document_id": "uuid",
  "message": "What is the main contribution?",
  "override_api_key": "",
  "override_base_url": "",
  "override_model": ""
}
```

`override_*` fields are optional and let frontend temporarily override backend `.env` defaults.

## Platform Notes

### macOS (Apple Silicon)
- PDF parsing now runs in the cloud via MinerU; no local Torch/MPS setup is required.
- If LaTeX compilation fails, install TeX Live + `latexmk` and Chinese fonts.

### Linux (CUDA)
- No GPU required for PDF parsing (MinerU is cloud-based).
- LLM translation still uses the OpenAI-compatible endpoint configured in `.env`.

### Windows
- Use `scripts/setup_windows.ps1`
- Install TeX Live + `latexmk` and ensure executable in PATH.

## Current MVP Boundaries

- Upload processing is still synchronous in request path (no background job handoff yet).
- Document state is in-memory and resets when backend restarts.
- Reference extraction is heuristic (section/line-pattern based), not a full citation parser.
- Frontend now supports panel toggles and premium shortcuts, but no account-tier gating yet.
